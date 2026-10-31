from werkzeug.security import generate_password_hash
from sqlalchemy.exc import IntegrityError

from models import (
    db,
    Organization,
    User,
    RoleEnum,
    Template,
    TemplateItem,
    StoreItem,
    Job,
    JobStatusEnum,
    PickList,
    PickListItem,
)
from utils.tenant_scope import set_current_org_id


def _seed_two_orgs(app_instance):
    with app_instance.app_context():
        org_a = Organization(name="Org A", slug="org-a")
        org_b = Organization(name="Org B", slug="org-b")
        db.session.add_all([org_a, org_b])
        db.session.flush()

        user_a = User(
            username="a_admin@example.com",
            password_hash=generate_password_hash("Password123!"),
            role=RoleEnum.ADMIN,
            organization_id=org_a.id,
        )
        user_b = User(
            username="b_admin@example.com",
            password_hash=generate_password_hash("Password123!"),
            role=RoleEnum.ADMIN,
            organization_id=org_b.id,
        )
        db.session.add_all([user_a, user_b])
        db.session.flush()

        tpl_a = Template(name="TA", engine_type="E", organization_id=org_a.id)
        tpl_b = Template(name="TB", engine_type="E", organization_id=org_b.id)
        db.session.add_all([tpl_a, tpl_b])
        db.session.flush()

        ti_a = TemplateItem(
            template_id=tpl_a.id,
            organization_id=org_a.id,
            section="A",
            pos=1,
            part_no="PA-1",
            name="Part A",
            qty=1,
        )
        ti_b = TemplateItem(
            template_id=tpl_b.id,
            organization_id=org_b.id,
            section="A",
            pos=1,
            part_no="PB-1",
            name="Part B",
            qty=1,
        )
        db.session.add_all([ti_a, ti_b])
        db.session.flush()

        store_a = StoreItem(template_item_id=ti_a.id, organization_id=org_a.id, barcode="CODE-A")
        store_b = StoreItem(template_item_id=ti_b.id, organization_id=org_b.id, barcode="CODE-B")
        db.session.add_all([store_a, store_b])

        job_a = Job(
            organization_id=org_a.id,
            job_pack_id="JPA",
            job_number="JNA",
            template_id=tpl_a.id,
            created_by_id=user_a.id,
            status=JobStatusEnum.PRE_SURVEY,
        )
        job_b = Job(
            organization_id=org_b.id,
            job_pack_id="JPB",
            job_number="JNB",
            template_id=tpl_b.id,
            created_by_id=user_b.id,
            status=JobStatusEnum.PRE_SURVEY,
        )
        db.session.add_all([job_a, job_b])
        db.session.flush()

        pl_a = PickList(job_id=job_a.id, organization_id=org_a.id, created_by_id=user_a.id)
        pl_b = PickList(job_id=job_b.id, organization_id=org_b.id, created_by_id=user_b.id)
        db.session.add_all([pl_a, pl_b])
        db.session.flush()

        pli_a = PickListItem(
            pick_list_id=pl_a.id,
            organization_id=org_a.id,
            part_no="PA-1",
            name="Part A",
            qty_required=1,
            stock_at_issue=0,
        )
        pli_b = PickListItem(
            pick_list_id=pl_b.id,
            organization_id=org_b.id,
            part_no="PB-1",
            name="Part B",
            qty_required=1,
            stock_at_issue=0,
        )
        db.session.add_all([pli_a, pli_b])
        db.session.commit()

        return {
            "org_a_id": org_a.id,
            "org_b_id": org_b.id,
            "user_a_id": user_a.id,
            "user_b_id": user_b.id,
            "store_a_id": store_a.id,
            "store_b_id": store_b.id,
            "picklist_a_id": pl_a.id,
            "picklist_b_id": pl_b.id,
            "pickitem_a_id": pli_a.id,
            "pickitem_b_id": pli_b.id,
        }


def _login_as(client, user_id: int):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def test_session_get_is_tenant_safe(app_for_tests):
    ids = _seed_two_orgs(app_for_tests)
    with app_for_tests.app_context():
        set_current_org_id(ids["org_a_id"])
        try:
            assert db.session.get(StoreItem, ids["store_a_id"]) is not None
            assert db.session.get(PickList, ids["picklist_a_id"]) is not None
            assert db.session.get(PickListItem, ids["pickitem_a_id"]) is not None

            assert db.session.get(StoreItem, ids["store_b_id"]) is None
            assert db.session.get(PickList, ids["picklist_b_id"]) is None
            assert db.session.get(PickListItem, ids["pickitem_b_id"]) is None
        finally:
            set_current_org_id(None)


def test_cross_tenant_picklist_read_is_404(app_for_tests, client):
    ids = _seed_two_orgs(app_for_tests)
    _login_as(client, ids["user_a_id"])
    res = client.get(f"/stores/picklists/{ids['picklist_b_id']}")
    assert res.status_code == 404


def test_cross_tenant_store_update_is_blocked(app_for_tests, client):
    ids = _seed_two_orgs(app_for_tests)
    _login_as(client, ids["user_a_id"])

    with app_for_tests.app_context():
        before = StoreItem.query.filter_by(id=ids["store_b_id"]).first()
        assert before is not None
        assert before.bin_location in (None, "")

    res = client.post(
        "/admin/stores/update",
        data={f"bin_{ids['store_b_id']}": "HACKED", "view": "master"},
        follow_redirects=False,
    )
    assert res.status_code == 302

    with app_for_tests.app_context():
        after = StoreItem.query.filter_by(id=ids["store_b_id"]).first()
        assert after is not None
        assert after.bin_location in (None, "")


def test_barcode_uniqueness_is_per_org(app_for_tests):
    ids = _seed_two_orgs(app_for_tests)
    with app_for_tests.app_context():
        tpl_a = Template.query.filter_by(organization_id=ids["org_a_id"]).first()
        tpl_b = Template.query.filter_by(organization_id=ids["org_b_id"]).first()
        assert tpl_a and tpl_b

        ti_a1 = TemplateItem(template_id=tpl_a.id, organization_id=ids["org_a_id"], section="A", pos=10, part_no="PA-10", name="PA10", qty=1)
        ti_a2 = TemplateItem(template_id=tpl_a.id, organization_id=ids["org_a_id"], section="A", pos=11, part_no="PA-11", name="PA11", qty=1)
        ti_a3 = TemplateItem(template_id=tpl_a.id, organization_id=ids["org_a_id"], section="A", pos=12, part_no="PA-12", name="PA12", qty=1)
        ti_b1 = TemplateItem(template_id=tpl_b.id, organization_id=ids["org_b_id"], section="A", pos=10, part_no="PB-10", name="PB10", qty=1)
        db.session.add_all([ti_a1, ti_a2, ti_a3, ti_b1])
        db.session.flush()

        # Same barcode across different orgs should be allowed.
        s_cross = StoreItem(
            template_item_id=ti_b1.id,
            organization_id=ids["org_b_id"],
            barcode="DUP-X-ORG",
        )
        db.session.add(s_cross)
        db.session.flush()

        s_other_org = StoreItem(
            template_item_id=ti_a1.id,
            organization_id=ids["org_a_id"],
            barcode="DUP-X-ORG",
        )
        db.session.add(s_other_org)
        db.session.flush()

        # Same barcode in same org should fail.
        s_same_org = StoreItem(
            template_item_id=ti_a2.id,
            organization_id=ids["org_a_id"],
            barcode="ONLY-ONE-PER-ORG",
        )
        db.session.add(s_same_org)
        db.session.flush()

        dup_same_org = StoreItem(
            template_item_id=ti_a3.id,
            organization_id=ids["org_a_id"],
            barcode="ONLY-ONE-PER-ORG",
        )
        db.session.add(dup_same_org)
        try:
            db.session.flush()
            assert False, "Expected same-org duplicate barcode to fail"
        except IntegrityError:
            db.session.rollback()
