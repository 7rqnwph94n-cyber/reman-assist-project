"""
QuickBooks Online integration service.

Handles OAuth2 flow, token management, and API calls for invoice/expense sync.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any, List
import requests
import logging

from flask import current_app

from models import (
    db,
    QuickBooksConnection,
    QuickBooksSyncLog,
    QuickBooksCustomerMap,
    Job,
    PartRequirement,
    QBSyncStatusEnum,
    QBSyncTypeEnum,
    QuickBooksEnvironmentEnum,
)
from services.encryption import TokenEncryption

logger = logging.getLogger(__name__)


def _load_qb_sdk():
    try:
        from intuitlib.client import AuthClient  # type: ignore[import-not-found]
        from intuitlib.enums import Scopes  # type: ignore[import-not-found]
        return AuthClient, Scopes, None
    except Exception as exc:
        return None, None, exc


def is_quickbooks_sdk_available() -> bool:
    auth_client_cls, scopes_cls, _err = _load_qb_sdk()
    return auth_client_cls is not None and scopes_cls is not None


def _require_quickbooks_sdk() -> None:
    if is_quickbooks_sdk_available():
        return
    _auth_client_cls, _scopes_cls, import_error = _load_qb_sdk()
    raise QuickBooksError(
        "QuickBooks SDK dependency is missing. Install `intuit-oauth` to enable QuickBooks integration.",
        code="QB_SDK_MISSING",
        details={"import_error": str(import_error)},
    )


class QuickBooksError(Exception):
    """Custom exception for QB API errors."""

    def __init__(self, message: str, code: str = None, details: dict = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class QuickBooksService:
    """
    Handles all QuickBooks API interactions for an organization.

    Usage:
        qb = QuickBooksService(organization_id)
        success, invoice_id, error = qb.create_invoice(job)
    """

    # QB API base URLs
    BASE_URLS = {
        "sandbox": "https://sandbox-quickbooks.api.intuit.com",
        "production": "https://quickbooks.api.intuit.com",
    }

    def __init__(self, organization_id: int):
        _require_quickbooks_sdk()
        self.organization_id = organization_id
        self.connection = self._get_connection()
        self._access_token = None

    def _get_connection(self) -> QuickBooksConnection:
        """Fetch active QB connection for this org."""
        conn = QuickBooksConnection.query.filter_by(
            organization_id=self.organization_id, is_active=True
        ).first()
        if not conn:
            raise QuickBooksError("QuickBooks not connected for this organization")
        return conn

    @property
    def base_url(self) -> str:
        env = (
            self.connection.environment.value
            if self.connection.environment
            else "sandbox"
        )
        return self.BASE_URLS.get(env, self.BASE_URLS["sandbox"])

    @property
    def api_url(self) -> str:
        return f"{self.base_url}/v3/company/{self.connection.realm_id}"

    def _get_auth_client(self):
        """Create IntuitLib auth client."""
        auth_client_cls, _scopes_cls, _err = _load_qb_sdk()
        if auth_client_cls is None:
            _require_quickbooks_sdk()
        env = (
            self.connection.environment.value
            if self.connection.environment
            else "sandbox"
        )
        return auth_client_cls(
            client_id=current_app.config["QUICKBOOKS_CLIENT_ID"],
            client_secret=current_app.config["QUICKBOOKS_CLIENT_SECRET"],
            redirect_uri=current_app.config["QUICKBOOKS_REDIRECT_URI"],
            environment=env,
        )

    def _ensure_valid_token(self) -> str:
        """Get valid access token, refreshing if needed."""
        # Check if token needs refresh (with 5 minute buffer)
        buffer = timedelta(minutes=5)
        now = datetime.now(timezone.utc)

        # Handle naive datetime from DB
        expires_at = self.connection.token_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at <= now + buffer:
            self._refresh_tokens()

        return TokenEncryption.decrypt(self.connection.access_token_encrypted)

    def _refresh_tokens(self) -> None:
        """Refresh access token using refresh token."""
        logger.info(f"Refreshing QB tokens for org {self.organization_id}")

        auth_client = self._get_auth_client()
        refresh_token = TokenEncryption.decrypt(self.connection.refresh_token_encrypted)

        try:
            auth_client.refresh(refresh_token=refresh_token)
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            self.connection.is_active = False
            db.session.commit()
            raise QuickBooksError(
                "QuickBooks connection expired. Please reconnect.", code="TOKEN_EXPIRED"
            )

        # Update stored tokens
        self.connection.access_token_encrypted = TokenEncryption.encrypt(
            auth_client.access_token
        )
        self.connection.refresh_token_encrypted = TokenEncryption.encrypt(
            auth_client.refresh_token
        )
        self.connection.token_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=3600
        )

        db.session.commit()
        logger.info(f"QB tokens refreshed for org {self.organization_id}")

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: dict = None,
        params: dict = None,
    ) -> dict:
        """Make authenticated request to QB API."""
        access_token = self._ensure_valid_token()

        url = f"{self.api_url}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=data,
            params=params,
            timeout=30,
        )

        if response.status_code >= 400:
            error_data = response.json() if response.content else {}
            fault = error_data.get("Fault", {})
            errors = fault.get("Error", [{}])
            error_msg = (
                errors[0].get("Message", "Unknown QB error")
                if errors
                else "Unknown QB error"
            )
            error_code = errors[0].get("code", "UNKNOWN") if errors else "UNKNOWN"

            logger.error(f"QB API error: {error_code} - {error_msg}")
            raise QuickBooksError(error_msg, code=error_code, details=error_data)

        return response.json()

    # ─────────────────────────────────────────
    # Customer Management
    # ─────────────────────────────────────────

    def _normalize_customer_name(self, name: str) -> str:
        """Normalize customer name for matching."""
        return (name or "").strip().lower()

    def find_or_create_customer(self, customer_name: str) -> Tuple[str, str]:
        """
        Find existing customer in QB or create new one.

        Returns: (qb_customer_id, qb_display_name)
        """
        if not customer_name:
            raise QuickBooksError("Customer name is required")

        normalized = self._normalize_customer_name(customer_name)

        # Check local cache first
        cached = QuickBooksCustomerMap.query.filter_by(
            organization_id=self.organization_id,
            customer_name_normalized=normalized,
        ).first()

        if cached:
            return cached.qb_customer_id, cached.qb_display_name

        # Search QB for existing customer
        # Escape single quotes for QB query
        escaped_name = customer_name.replace("'", "\\'")
        query = f"SELECT * FROM Customer WHERE DisplayName = '{escaped_name}'"
        try:
            result = self._make_request("GET", "query", params={"query": query})
            customers = result.get("QueryResponse", {}).get("Customer", [])

            if customers:
                qb_customer = customers[0]
                qb_id = qb_customer["Id"]
                display_name = qb_customer.get("DisplayName", customer_name)

                # Cache the mapping
                self._cache_customer(customer_name, qb_id, display_name)
                return qb_id, display_name
        except QuickBooksError:
            pass  # Customer not found, will create

        # Create new customer if auto_create enabled
        if not self.connection.auto_create_customers:
            raise QuickBooksError(
                f"Customer '{customer_name}' not found in QuickBooks. "
                "Auto-create is disabled.",
                code="CUSTOMER_NOT_FOUND",
            )

        customer_data = {
            "DisplayName": customer_name[:100],  # QB limit
            "CompanyName": customer_name[:100],
        }

        result = self._make_request("POST", "customer", data=customer_data)
        qb_customer = result.get("Customer", {})
        qb_id = qb_customer["Id"]
        display_name = qb_customer.get("DisplayName", customer_name)

        # Cache the mapping
        self._cache_customer(customer_name, qb_id, display_name)

        logger.info(f"Created QB customer '{customer_name}' with ID {qb_id}")
        return qb_id, display_name

    def _cache_customer(self, name: str, qb_id: str, display_name: str) -> None:
        """Cache customer mapping locally."""
        mapping = QuickBooksCustomerMap(
            organization_id=self.organization_id,
            customer_name=name,
            customer_name_normalized=self._normalize_customer_name(name),
            qb_customer_id=qb_id,
            qb_display_name=display_name,
        )
        db.session.add(mapping)
        db.session.commit()

    # ─────────────────────────────────────────
    # Invoice Creation
    # ─────────────────────────────────────────

    def create_or_update_invoice(
        self,
        job: Job,
        user_id: int = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Create or update QB invoice for a job.

        Returns: (success, qb_invoice_id, error_message)
        """
        try:
            # Find or create customer
            customer_id, _ = self.find_or_create_customer(job.customer_name)

            # Build line items from costing sheet or BOM
            line_items = self._build_invoice_lines(job)

            if not line_items:
                return False, None, "No billable items found for this job"

            # Build invoice payload
            invoice_data = self._build_invoice_payload(job, customer_id, line_items)

            # Create or update
            if job.qb_invoice_id:
                # Update existing - need to fetch SyncToken first
                existing = self._make_request("GET", f"invoice/{job.qb_invoice_id}")
                sync_token = existing.get("Invoice", {}).get("SyncToken", "0")
                invoice_data["Id"] = job.qb_invoice_id
                invoice_data["SyncToken"] = sync_token
                invoice_data["sparse"] = True

            result = self._make_request("POST", "invoice", data=invoice_data)
            invoice = result.get("Invoice", {})

            qb_id = invoice["Id"]
            doc_number = invoice.get("DocNumber", "")

            # Update job record
            job.qb_invoice_id = qb_id
            job.qb_invoice_number = doc_number
            job.qb_sync_status = QBSyncStatusEnum.SYNCED
            job.qb_last_sync_at = datetime.now(timezone.utc)
            job.qb_sync_error = None

            # Build deep link URL
            env = self.connection.environment.value if self.connection.environment else "sandbox"
            if env == "production":
                job.qb_invoice_url = f"https://qbo.intuit.com/app/invoice?txnId={qb_id}"
            else:
                job.qb_invoice_url = (
                    f"https://app.sandbox.qbo.intuit.com/app/invoice?txnId={qb_id}"
                )

            # Log success
            self._log_sync(
                sync_type=QBSyncTypeEnum.INVOICE,
                entity_type="Job",
                entity_id=job.id,
                qb_id=qb_id,
                qb_doc_number=doc_number,
                status="success",
                user_id=user_id,
                request_payload=invoice_data,
                response_payload=result,
            )

            db.session.commit()

            logger.info(f"Synced job {job.job_number} to QB invoice {doc_number}")
            return True, qb_id, None

        except QuickBooksError as e:
            # Update job with error status
            job.qb_sync_status = QBSyncStatusEnum.FAILED
            job.qb_sync_error = str(e)

            # Log failure
            self._log_sync(
                sync_type=QBSyncTypeEnum.INVOICE,
                entity_type="Job",
                entity_id=job.id,
                status="failed",
                error_message=str(e),
                error_code=e.code,
                user_id=user_id,
            )

            db.session.commit()

            logger.error(f"Failed to sync job {job.job_number}: {e}")
            return False, None, str(e)

    def _build_invoice_lines(self, job: Job) -> List[Dict]:
        """Build invoice line items from job data."""
        lines = []

        # Try costing sheet first (more accurate pricing)
        if job.costing_sheet and job.costing_sheet.lines:
            for idx, line in enumerate(job.costing_sheet.lines, 1):
                if line.qty_required and line.qty_required > 0:
                    unit_price = float(line.price_cost or line.latest_cost or 0)
                    lines.append(
                        {
                            "LineNum": idx,
                            "Description": f"{line.part_description or line.oem_part_no or 'Part'}"[
                                :4000
                            ],
                            "Amount": round(unit_price * line.qty_required, 2),
                            "DetailType": "SalesItemLineDetail",
                            "SalesItemLineDetail": {
                                "Qty": line.qty_required,
                                "UnitPrice": unit_price,
                            },
                        }
                    )

        # Fall back to BOM/part requirements
        elif job.part_requirements:
            for idx, pr in enumerate(job.part_requirements, 1):
                if pr.qty_required and pr.qty_required > 0:
                    lines.append(
                        {
                            "LineNum": idx,
                            "Description": f"{pr.name or pr.part_no or 'Part'}"[:4000],
                            "Amount": 0,  # No pricing in BOM
                            "DetailType": "SalesItemLineDetail",
                            "SalesItemLineDetail": {
                                "Qty": pr.qty_required,
                                "UnitPrice": 0,
                            },
                        }
                    )

        return lines

    def _build_invoice_payload(
        self,
        job: Job,
        customer_id: str,
        line_items: List[Dict],
    ) -> Dict:
        """Build QB invoice API payload."""
        # Generate doc number with optional prefix
        prefix = self.connection.invoice_prefix or ""
        doc_number = f"{prefix}{job.job_number}"[:21]  # QB limit

        payload = {
            "CustomerRef": {"value": customer_id},
            "DocNumber": doc_number,
            "TxnDate": job.created_at.strftime("%Y-%m-%d") if job.created_at else None,
            "Line": line_items,
            "PrivateNote": f"Created from RemanAssist Job #{job.job_number}",
        }

        # Add custom field for engine if available
        if job.engine_type:
            payload["CustomerMemo"] = {"value": f"Engine: {job.engine_type}"}

        return payload

    # ─────────────────────────────────────────
    # Expense Sync (Parts Purchases)
    # ─────────────────────────────────────────

    def create_expense(
        self,
        part_requirements: List[PartRequirement],
        job: Job,
        user_id: int = None,
    ) -> Tuple[int, int, List[str]]:
        """
        Create expenses in QB for part purchases.

        Returns: (success_count, fail_count, errors)
        """
        success_count = 0
        fail_count = 0
        errors = []

        for pr in part_requirements:
            try:
                # Skip if already synced
                if pr.qb_expense_id:
                    continue

                # Try to get cost from costing lines
                unit_cost = 0
                if hasattr(pr, "costing_lines") and pr.costing_lines:
                    cl = pr.costing_lines[0]
                    unit_cost = float(cl.unit_cost_confirmed or cl.latest_cost or 0)

                if unit_cost == 0:
                    # Skip items with no cost
                    continue

                expense_data = {
                    "PaymentType": "Cash",
                    "TxnDate": (
                        pr.received_at.strftime("%Y-%m-%d")
                        if pr.received_at
                        else datetime.now().strftime("%Y-%m-%d")
                    ),
                    "Line": [
                        {
                            "DetailType": "AccountBasedExpenseLineDetail",
                            "Amount": round(unit_cost * (pr.qty_required or 1), 2),
                            "AccountBasedExpenseLineDetail": {
                                "AccountRef": {
                                    "value": self.connection.default_expense_account_id
                                    or "1"
                                },
                            },
                            "Description": f"Job #{job.job_number} - {pr.name or pr.part_no}"[
                                :4000
                            ],
                        }
                    ],
                    "PrivateNote": f"RemanAssist Part Req #{pr.id} for Job #{job.job_number}",
                }

                result = self._make_request("POST", "purchase", data=expense_data)
                purchase = result.get("Purchase", {})

                pr.qb_expense_id = purchase["Id"]
                pr.qb_last_sync_at = datetime.now(timezone.utc)

                self._log_sync(
                    sync_type=QBSyncTypeEnum.EXPENSE,
                    entity_type="PartRequirement",
                    entity_id=pr.id,
                    qb_id=purchase["Id"],
                    status="success",
                    user_id=user_id,
                )

                success_count += 1

            except QuickBooksError as e:
                fail_count += 1
                errors.append(f"Part {pr.part_no}: {e}")

                self._log_sync(
                    sync_type=QBSyncTypeEnum.EXPENSE,
                    entity_type="PartRequirement",
                    entity_id=pr.id,
                    status="failed",
                    error_message=str(e),
                    error_code=e.code,
                    user_id=user_id,
                )

        db.session.commit()
        return success_count, fail_count, errors

    # ─────────────────────────────────────────
    # Utility Methods
    # ─────────────────────────────────────────

    def test_connection(self) -> Tuple[bool, str]:
        """Test the QB connection by fetching company info."""
        try:
            result = self._make_request(
                "GET", "companyinfo/" + self.connection.realm_id
            )
            company = result.get("CompanyInfo", {})
            company_name = company.get("CompanyName", "Unknown")

            self.connection.company_name = company_name
            self.connection.last_test_at = datetime.now(timezone.utc)
            self.connection.last_test_status = "ok"
            self.connection.last_test_message = f"Connected to {company_name}"
            db.session.commit()

            return True, f"Connected to {company_name}"

        except QuickBooksError as e:
            self.connection.last_test_at = datetime.now(timezone.utc)
            self.connection.last_test_status = "fail"
            self.connection.last_test_message = str(e)
            db.session.commit()

            return False, str(e)

    def get_accounts(self, account_type: str = None) -> List[Dict]:
        """Fetch chart of accounts for configuration."""
        query = "SELECT * FROM Account"
        if account_type:
            query += f" WHERE AccountType = '{account_type}'"
        query += " MAXRESULTS 100"

        result = self._make_request("GET", "query", params={"query": query})
        return result.get("QueryResponse", {}).get("Account", [])

    def _log_sync(
        self,
        sync_type: QBSyncTypeEnum,
        entity_type: str,
        entity_id: int,
        qb_id: str = None,
        qb_doc_number: str = None,
        status: str = "pending",
        error_message: str = None,
        error_code: str = None,
        user_id: int = None,
        request_payload: dict = None,
        response_payload: dict = None,
    ) -> QuickBooksSyncLog:
        """Log sync attempt."""
        log = QuickBooksSyncLog(
            organization_id=self.organization_id,
            sync_type=sync_type,
            entity_type=entity_type,
            entity_id=entity_id,
            qb_id=qb_id,
            qb_doc_number=qb_doc_number,
            status=status,
            error_message=error_message,
            error_code=error_code,
            synced_by_id=user_id,
            request_payload=request_payload,
            response_payload=response_payload,
        )
        db.session.add(log)
        return log


# ─────────────────────────────────────────
# OAuth Flow Helpers
# ─────────────────────────────────────────


def get_oauth_client():
    """Create OAuth client for initial auth flow."""
    _require_quickbooks_sdk()
    auth_client_cls, _scopes_cls, _err = _load_qb_sdk()
    env = current_app.config.get("QUICKBOOKS_ENVIRONMENT", "sandbox")
    return auth_client_cls(
        client_id=current_app.config["QUICKBOOKS_CLIENT_ID"],
        client_secret=current_app.config["QUICKBOOKS_CLIENT_SECRET"],
        redirect_uri=current_app.config["QUICKBOOKS_REDIRECT_URI"],
        environment=env,
    )


def get_authorization_url() -> Tuple[str, str]:
    """
    Generate OAuth authorization URL.

    Returns: (auth_url, state_token)
    """
    auth_client = get_oauth_client()
    _auth_client_cls, scopes_cls, _err = _load_qb_sdk()
    if scopes_cls is None:
        _require_quickbooks_sdk()
        _auth_client_cls, scopes_cls, _err = _load_qb_sdk()
    scopes = [scopes_cls.ACCOUNTING]

    auth_url = auth_client.get_authorization_url(scopes)
    state = auth_client.state_token

    return auth_url, state


def exchange_code_for_tokens(
    code: str,
    realm_id: str,
    organization_id: int,
    user_id: int,
) -> QuickBooksConnection:
    """
    Exchange authorization code for tokens and create/update connection.
    """
    auth_client = get_oauth_client()
    auth_client.get_bearer_token(code, realm_id=realm_id)

    # Check for existing connection
    existing = QuickBooksConnection.query.filter_by(
        organization_id=organization_id
    ).first()

    if existing:
        # Update existing
        conn = existing
    else:
        # Create new
        conn = QuickBooksConnection(organization_id=organization_id)

    conn.realm_id = realm_id
    conn.access_token_encrypted = TokenEncryption.encrypt(auth_client.access_token)
    conn.refresh_token_encrypted = TokenEncryption.encrypt(auth_client.refresh_token)
    conn.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=3600)
    conn.refresh_token_expires_at = datetime.now(timezone.utc) + timedelta(days=100)
    conn.environment = QuickBooksEnvironmentEnum(
        current_app.config.get("QUICKBOOKS_ENVIRONMENT", "sandbox")
    )
    conn.is_active = True
    conn.connected_by_id = user_id
    conn.connected_at = datetime.now(timezone.utc)

    db.session.add(conn)
    db.session.commit()

    return conn
