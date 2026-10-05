import hashlib
import hmac

from app.services.zoom.usecases import url_validation_response, verify_signature

SECRET = "test-secret"


def test_url_validation_response_is_hmac_of_plain_token():
    res = url_validation_response(SECRET, "abc")
    assert res["plainToken"] == "abc"
    assert res["encryptedToken"] == hmac.new(b"test-secret", b"abc", hashlib.sha256).hexdigest()


def test_verify_signature():
    body = b'{"event":"meeting.participant_joined","payload":{}}'
    sig = "v0=" + hmac.new(b"test-secret", b"v0:1700000000:" + body, hashlib.sha256).hexdigest()
    assert verify_signature(SECRET, "1700000000", body, sig)
    assert not verify_signature(SECRET, "1700000001", body, sig)  # 타임스탬프가 다르면 실패
    assert not verify_signature(SECRET, "1700000000", body + b" ", sig)  # 본문이 1바이트라도 다르면 실패
    assert not verify_signature("other", "1700000000", body, sig)
