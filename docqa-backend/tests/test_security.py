from app.security import hash_password, verify_password


def test_hash_is_argon2id_and_not_the_password() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert password_hash.startswith("$argon2id$")
    assert "correct horse" not in password_hash


def test_same_password_hashes_differently_each_time() -> None:
    # A random salt per hash: equal passwords don't give equal hashes
    assert hash_password("s3cret-pass") != hash_password("s3cret-pass")


def test_verify_accepts_the_right_password_only() -> None:
    password_hash = hash_password("s3cret-pass")

    assert verify_password(password_hash, "s3cret-pass")
    assert not verify_password(password_hash, "s3cret-pasS")
