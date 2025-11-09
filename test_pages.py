#!/usr/bin/env python3
"""
Automated tests for all site pages
Tests both public and admin pages for 200/302/404 responses
"""

import sys
from app import create_app, db
from app.auth.models import User
from flask_login import login_user

app = create_app()

# Test routes configuration
PUBLIC_ROUTES = [
    ('/', 'Dashboard/Home'),
    ('/login', 'Login'),
    ('/register', 'Register'),
    ('/words', 'Words List'),
    ('/books', 'Books List'),
    ('/study/', 'Study Page'),
    ('/curriculum/', 'Curriculum'),
]

ADMIN_ROUTES = [
    ('/admin/', 'Admin Dashboard'),
    ('/admin/users', 'Admin Users'),
    ('/admin/curriculum', 'Admin Curriculum'),
    ('/admin/curriculum/levels', 'Admin Levels'),
    ('/admin/curriculum/modules', 'Admin Modules'),
    ('/admin/curriculum/lessons', 'Admin Lessons'),
    ('/admin/topics', 'Admin Topics'),
    ('/admin/collections', 'Admin Collections'),
    ('/admin/book-courses', 'Admin Book Courses'),
]

USER_ROUTES = [
    ('/study/collections', 'Study Collections'),
    ('/study/topics', 'Study Topics'),
]


def test_public_pages():
    """Test all public pages"""
    print("\n" + "="*80)
    print("TESTING PUBLIC PAGES")
    print("="*80)

    with app.test_client() as client:
        errors = []
        success = []

        for route, name in PUBLIC_ROUTES:
            try:
                response = client.get(route, follow_redirects=False)
                status = response.status_code

                if status in [200, 302, 308]:  # 308 = permanent redirect
                    success.append(f"✓ {name:30} {route:40} [{status}]")
                else:
                    errors.append(f"✗ {name:30} {route:40} [{status}]")

            except Exception as e:
                errors.append(f"✗ {name:30} {route:40} [ERROR: {str(e)[:50]}]")

        # Print results
        for msg in success:
            print(msg)

        if errors:
            print("\n" + "!"*80)
            print("ERRORS FOUND:")
            print("!"*80)
            for msg in errors:
                print(msg)
            return False
        else:
            print("\n✅ All public pages OK!")
            return True


def test_admin_pages():
    """Test all admin pages with admin user"""
    print("\n" + "="*80)
    print("TESTING ADMIN PAGES")
    print("="*80)

    with app.test_client() as client:
        with app.app_context():
            # Get admin user (first user is usually admin)
            admin = User.query.filter_by(is_admin=True).first()
            if not admin:
                admin = User.query.first()

            if not admin:
                print("⚠ No users found in database.")
                return False

            # Login as admin
            with client.session_transaction() as sess:
                sess['_user_id'] = str(admin.id)
                sess['_fresh'] = True

            errors = []
            success = []

            for route, name in ADMIN_ROUTES:
                try:
                    response = client.get(route, follow_redirects=False)
                    status = response.status_code

                    if status in [200, 302, 308]:  # 308 = permanent redirect
                        success.append(f"✓ {name:30} {route:40} [{status}]")
                    elif status == 404:
                        errors.append(f"⚠ {name:30} {route:40} [404 - Not Found]")
                    else:
                        errors.append(f"✗ {name:30} {route:40} [{status}]")

                except Exception as e:
                    errors.append(f"✗ {name:30} {route:40} [ERROR: {str(e)[:50]}]")

            # Print results
            for msg in success:
                print(msg)

            if errors:
                print("\n" + "!"*80)
                print("ERRORS FOUND:")
                print("!"*80)
                for msg in errors:
                    print(msg)
                return False
            else:
                print("\n✅ All admin pages OK!")
                return True


def test_user_pages():
    """Test user-specific pages"""
    print("\n" + "="*80)
    print("TESTING USER PAGES")
    print("="*80)

    with app.test_client() as client:
        with app.app_context():
            # Get any regular user
            user = User.query.filter_by(is_admin=False).first()
            if not user:
                # Try to get admin as fallback
                user = User.query.first()

            if not user:
                print("⚠ No users found in database.")
                return False

            # Login as user
            with client.session_transaction() as sess:
                sess['_user_id'] = str(user.id)
                sess['_fresh'] = True

            errors = []
            success = []

            for route, name in USER_ROUTES:
                try:
                    response = client.get(route, follow_redirects=False)
                    status = response.status_code

                    if status in [200, 302]:
                        success.append(f"✓ {name:30} {route:40} [{status}]")
                    else:
                        errors.append(f"✗ {name:30} {route:40} [{status}]")

                except Exception as e:
                    errors.append(f"✗ {name:30} {route:40} [ERROR: {str(e)[:50]}]")

            # Print results
            for msg in success:
                print(msg)

            if errors:
                print("\n" + "!"*80)
                print("ERRORS FOUND:")
                print("!"*80)
                for msg in errors:
                    print(msg)
                return False
            else:
                print("\n✅ All user pages OK!")
                return True


def run_all_tests():
    """Run all tests"""
    print("\n" + "█"*80)
    print("AUTOMATED SITE TESTING")
    print("█"*80)

    results = []

    # Test public pages
    results.append(("Public Pages", test_public_pages()))

    # Test admin pages
    results.append(("Admin Pages", test_admin_pages()))

    # Test user pages
    results.append(("User Pages", test_user_pages()))

    # Final summary
    print("\n" + "█"*80)
    print("TEST SUMMARY")
    print("█"*80)

    all_passed = True
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name:30} {status}")
        if not passed:
            all_passed = False

    print("█"*80)

    if all_passed:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(run_all_tests())
