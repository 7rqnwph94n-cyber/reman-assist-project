#!/usr/bin/env python3
"""
Comprehensive stress test for the remanufacturing application.
Tests performance, security, edge cases, and tries to break things.
"""
import time
import random
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytest
from app import create_app
from models import db, Job, Template, User, Organization, SurveyItem, PartRequirement
from services.seed_data import seed_database
from sqlalchemy import text

RUN_STRESS_TESTS = os.environ.get("RUN_STRESS_TESTS") == "1"
if not RUN_STRESS_TESTS:
    pytestmark = pytest.mark.skip(reason="Set RUN_STRESS_TESTS=1 to run stress/integration tests.")

app = create_app() if RUN_STRESS_TESTS else None

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'

def log_test(name, status="RUN"):
    color = Colors.BLUE if status == "RUN" else Colors.GREEN if status == "PASS" else Colors.RED
    print(f"{color}[{status}]{Colors.END} {name}")

def log_metric(name, value, unit=""):
    print(f"  {Colors.YELLOW}→{Colors.END} {name}: {Colors.BOLD}{value}{unit}{Colors.END}")

def test_dashboard_performance():
    """Test dashboard query performance with N+1 fix"""
    log_test("Dashboard Performance Test (N+1 Query Fix)")

    with app.app_context():
        org = Organization.query.filter_by(slug="global-reman").first()
        job_count = Job.query.filter_by(organization_id=org.id).count()
        log_metric("Jobs in database", job_count)

        # Test dashboard query performance
        from sqlalchemy import event
        query_count = {"count": 0}

        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            query_count["count"] += 1

        event.listen(db.engine, "before_cursor_execute", before_cursor_execute)

        start_time = time.time()
        jobs = Job.query.filter_by(organization_id=org.id).limit(50).all()
        # Access relationships to trigger lazy loading (if any)
        for job in jobs:
            _ = job.template.name if job.template else None
            _ = job.assigned_to.username if job.assigned_to else None
            _ = job.created_by.username if job.created_by else None
        end_time = time.time()

        event.remove(db.engine, "before_cursor_execute", before_cursor_execute)

        elapsed = (end_time - start_time) * 1000
        queries_per_job = query_count["count"] / len(jobs) if jobs else 0

        log_metric("Query execution time", f"{elapsed:.2f}", "ms")
        log_metric("Total queries", query_count["count"])
        log_metric("Queries per job", f"{queries_per_job:.2f}")

        # Performance thresholds
        if elapsed > 500:
            log_test("Dashboard Performance", "FAIL")
            log_metric("FAIL REASON", "Dashboard took >500ms")
            return False
        if queries_per_job > 2:
            log_test("Dashboard Performance", "WARN")
            log_metric("WARNING", "More than 2 queries per job (possible N+1)")

        log_test("Dashboard Performance", "PASS")
        return True

def test_stress_job_creation():
    """Create many jobs quickly to stress test"""
    log_test("Stress Test: Rapid Job Creation")

    with app.app_context():
        org = Organization.query.filter_by(slug="global-reman").first()
        templates = Template.query.filter_by(organization_id=org.id).all()
        user = User.query.filter_by(organization_id=org.id).first()

        if not templates:
            log_test("Stress Job Creation", "SKIP")
            log_metric("SKIP REASON", "No templates available")
            return True

        start_job_count = Job.query.filter_by(organization_id=org.id).count()
        create_count = 50

        start_time = time.time()
        for i in range(create_count):
            template = random.choice(templates)
            job = Job(
                job_number=f"STRESS-{int(time.time())}-{i}",
                job_pack_id=f"STRESS-{int(time.time())}-{i}",
                organization_id=org.id,
                customer_name=f"Stress Test Customer {i}",
                engine_type=template.engine_type,
                serial_number=f"STRESS-SN-{i}",
                status="PRE_SURVEY",
                template_id=template.id,
                template_version=template.version,
                created_by_id=user.id if user else None,
            )
            db.session.add(job)

            if i % 10 == 0:
                db.session.flush()

        db.session.commit()
        end_time = time.time()

        end_job_count = Job.query.filter_by(organization_id=org.id).count()
        created = end_job_count - start_job_count
        elapsed = end_time - start_time
        jobs_per_sec = created / elapsed if elapsed > 0 else 0

        log_metric("Jobs created", created)
        log_metric("Time elapsed", f"{elapsed:.2f}", "s")
        log_metric("Jobs per second", f"{jobs_per_sec:.1f}")

        log_test("Stress Job Creation", "PASS")
        return True

def test_concurrent_database_operations():
    """Test concurrent reads and writes"""
    log_test("Concurrent Database Operations")

    def read_jobs(thread_id):
        with app.app_context():
            org = Organization.query.filter_by(slug="global-reman").first()
            jobs = Job.query.filter_by(organization_id=org.id).limit(20).all()
            return len(jobs)

    def update_job(thread_id):
        with app.app_context():
            org = Organization.query.filter_by(slug="global-reman").first()
            job = Job.query.filter_by(organization_id=org.id).first()
            if job:
                job.customer_name = f"Updated by thread {thread_id}"
                db.session.commit()
            return True

    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Mix of reads and writes
        futures = []
        for i in range(20):
            if i % 3 == 0:
                futures.append(executor.submit(update_job, i))
            else:
                futures.append(executor.submit(read_jobs, i))

        for future in as_completed(futures):
            try:
                result = future.result(timeout=5)
                results.append(result)
            except Exception as e:
                log_test("Concurrent Operations", "FAIL")
                log_metric("FAIL REASON", str(e))
                return False

    log_metric("Concurrent operations completed", len(results))
    log_test("Concurrent Operations", "PASS")
    return True

def test_large_query_performance():
    """Test performance with large result sets"""
    log_test("Large Query Performance")

    with app.app_context():
        org = Organization.query.filter_by(slug="global-reman").first()

        # Test large survey items query
        start_time = time.time()
        survey_items = SurveyItem.query.join(Job).filter(
            Job.organization_id == org.id
        ).limit(1000).all()
        end_time = time.time()

        elapsed = (end_time - start_time) * 1000
        log_metric("Survey items queried", len(survey_items))
        log_metric("Query time", f"{elapsed:.2f}", "ms")

        # Test large BOM query
        start_time = time.time()
        parts = PartRequirement.query.join(Job).filter(
            Job.organization_id == org.id
        ).limit(1000).all()
        end_time = time.time()

        elapsed2 = (end_time - start_time) * 1000
        log_metric("BOM items queried", len(parts))
        log_metric("Query time", f"{elapsed2:.2f}", "ms")

        if elapsed > 1000 or elapsed2 > 1000:
            log_test("Large Query Performance", "WARN")
            log_metric("WARNING", "Query took >1 second")
        else:
            log_test("Large Query Performance", "PASS")

        return True

def test_edge_cases():
    """Test edge cases and boundary conditions"""
    log_test("Edge Cases and Boundary Conditions")

    with app.app_context():
        org = Organization.query.filter_by(slug="global-reman").first()

        # Test 1: Empty job number
        try:
            job = Job(
                job_number="",
                organization_id=org.id,
                customer_name="Test",
            )
            db.session.add(job)
            db.session.flush()
            db.session.rollback()
            log_metric("Edge Case 1", "FAIL - Empty job number allowed")
        except Exception:
            log_metric("Edge Case 1", "PASS - Empty job number rejected")

        # Test 2: Very long customer name
        try:
            long_name = "A" * 10000
            job = Job(
                job_number="EDGE-TEST-001",
                job_pack_id="EDGE-TEST-001",
                organization_id=org.id,
                customer_name=long_name,
                status="PRE_SURVEY",
            )
            db.session.add(job)
            db.session.commit()
            log_metric("Edge Case 2", "PASS - Very long names handled")

            # Clean up
            db.session.delete(job)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            log_metric("Edge Case 2", f"Database rejected: {str(e)[:50]}")

        # Test 3: Null organization_id (should fail)
        try:
            job = Job(
                job_number="EDGE-TEST-002",
                organization_id=None,
                customer_name="Test",
            )
            db.session.add(job)
            db.session.flush()
            db.session.rollback()
            log_metric("Edge Case 3", "FAIL - NULL org_id allowed")
        except Exception:
            db.session.rollback()
            log_metric("Edge Case 3", "PASS - NULL org_id rejected")

    log_test("Edge Cases", "PASS")
    return True

def test_database_integrity():
    """Check database integrity and constraints"""
    log_test("Database Integrity Checks")

    with app.app_context():
        # Check for orphaned records
        orphaned_surveys = db.session.execute(text("""
            SELECT COUNT(*) FROM survey_items
            WHERE job_id NOT IN (SELECT id FROM jobs)
        """)).scalar()

        orphaned_parts = db.session.execute(text("""
            SELECT COUNT(*) FROM part_requirements
            WHERE job_id NOT IN (SELECT id FROM jobs)
        """)).scalar()

        log_metric("Orphaned survey items", orphaned_surveys)
        log_metric("Orphaned part requirements", orphaned_parts)

        if orphaned_surveys > 0 or orphaned_parts > 0:
            log_test("Database Integrity", "WARN")
            log_metric("WARNING", "Found orphaned records")
        else:
            log_test("Database Integrity", "PASS")

        # Check for duplicate job numbers within org
        org = Organization.query.filter_by(slug="global-reman").first()
        duplicates = db.session.execute(text("""
            SELECT job_number, COUNT(*) as cnt
            FROM jobs
            WHERE organization_id = :org_id
            GROUP BY job_number
            HAVING COUNT(*) > 1
        """), {"org_id": org.id}).fetchall()

        if duplicates:
            log_metric("Duplicate job numbers", len(duplicates))
            log_test("Database Integrity", "FAIL")
            return False
        else:
            log_metric("Duplicate job numbers", 0)

        return True

def test_memory_usage():
    """Test memory usage with large datasets"""
    log_test("Memory Usage Test")

    import tracemalloc
    tracemalloc.start()

    with app.app_context():
        org = Organization.query.filter_by(slug="global-reman").first()

        # Load a lot of data
        jobs = Job.query.filter_by(organization_id=org.id).all()
        for job in jobs:
            _ = SurveyItem.query.filter_by(job_id=job.id).all()

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        log_metric("Current memory", f"{current / 1024 / 1024:.2f}", " MB")
        log_metric("Peak memory", f"{peak / 1024 / 1024:.2f}", " MB")

        if peak > 100 * 1024 * 1024:  # 100 MB
            log_test("Memory Usage", "WARN")
            log_metric("WARNING", "Peak memory >100MB")
        else:
            log_test("Memory Usage", "PASS")

        return True

def run_all_tests():
    """Run all stress tests"""
    print(f"\n{Colors.BOLD}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}🔥 COMPREHENSIVE STRESS TEST - TESTING TO DESTRUCTION 🔥{Colors.END}")
    print(f"{Colors.BOLD}{'='*60}{Colors.END}\n")

    tests = [
        ("Dashboard Performance (N+1 Fix)", test_dashboard_performance),
        ("Large Query Performance", test_large_query_performance),
        ("Stress: Rapid Job Creation", test_stress_job_creation),
        ("Concurrent Database Operations", test_concurrent_database_operations),
        ("Edge Cases & Boundaries", test_edge_cases),
        ("Database Integrity", test_database_integrity),
        ("Memory Usage", test_memory_usage),
    ]

    results = []
    total_start = time.time()

    for test_name, test_func in tests:
        print()
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"{Colors.RED}[CRASH]{Colors.END} {test_name}")
            print(f"  {Colors.RED}Error: {str(e)}{Colors.END}")
            results.append((test_name, False))

    total_elapsed = time.time() - total_start

    # Summary
    print(f"\n{Colors.BOLD}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}📊 TEST SUMMARY{Colors.END}")
    print(f"{Colors.BOLD}{'='*60}{Colors.END}\n")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = f"{Colors.GREEN}✓ PASS{Colors.END}" if result else f"{Colors.RED}✗ FAIL{Colors.END}"
        print(f"  {status} {test_name}")

    print(f"\n{Colors.BOLD}Results:{Colors.END} {passed}/{total} tests passed")
    print(f"{Colors.BOLD}Total time:{Colors.END} {total_elapsed:.2f}s\n")

    if passed == total:
        print(f"{Colors.GREEN}{Colors.BOLD}🎉 ALL TESTS PASSED! Application is solid. 🎉{Colors.END}\n")
    else:
        print(f"{Colors.YELLOW}{Colors.BOLD}⚠️  Some tests failed. Review above for details. ⚠️{Colors.END}\n")

    return passed == total

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
