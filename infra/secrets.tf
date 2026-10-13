# Secret used to sign and verify JWT access/refresh tokens (shared by all services)
resource "random_password" "jwt_secret" {
  length  = 48
  special = false
}

# Initial password for the seeded admin account (6 characters, like all generated passwords)
resource "random_password" "admin" {
  length  = 6
  special = false
}
