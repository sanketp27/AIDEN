"""
Helper script to generate test JWT tokens for AIDEN
Use this during development to get authentication tokens
"""
from src.api.middleware import create_access_token
from src.models.user import UserRole
import sys


def generate_token(user_id: str = "test_user", role: str = "user", email: str = None):
    """Generate a JWT token for testing"""

    # Validate role
    try:
        user_role = UserRole(role)
    except ValueError:
        print(f"Error: Invalid role '{role}'. Must be one of: executive, user, developer")
        sys.exit(1)

    # Generate token
    token, expires_in = create_access_token(
        user_id=user_id,
        role=user_role,
        email=email
    )

    print("=" * 70)
    print("AIDEN v2.0 - JWT Token Generated")
    print("=" * 70)
    print(f"User ID: {user_id}")
    print(f"Role: {role}")
    print(f"Email: {email or 'N/A'}")
    print(f"Expires in: {expires_in // 60} minutes")
    print("=" * 70)
    print("\nJWT Token:")
    print(token)
    print("\=" * 70)
    print("\nHow to use:")
    print("1. Copy the token above")
    print("2. In Streamlit UI: Paste into the JWT Token field in sidebar")
    print("3. In API calls: Add header: Authorization: Bearer <token>")
    print("\nExample curl command:")
    print(f'curl -H "Authorization: Bearer {token}" http://localhost:8000/tasks')
    print("=" * 70)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate JWT token for AIDEN")
    parser.add_argument("--user-id", default="test_user", help="User ID (default: test_user)")
    parser.add_argument("--role", default="user", choices=["executive", "user", "developer"],
                       help="User role (default: user)")
    parser.add_argument("--email", help="User email (optional)")

    args = parser.parse_args()

    generate_token(args.user_id, args.role, args.email)
