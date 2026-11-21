import pytest

from retro_mine import redact

# Secret-looking strings are assembled at runtime so this file itself does not
# trip secret scanners.
GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
GH_PAT = "github_pat_" + "11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz"
SK = "sk-" + "proj-Abc123Def456Ghi789Jkl012"
SK_ANT = "sk-ant-" + "api03-AbCdEf0123456789-xyz_ABCdef"
SLACK = "xoxb-" + "123456789012-1234567890123-AbCdEfGhIjKlMnOp"
AWS = "AKIA" + "IOSFODNN7EXAMPLE"
JWT = "eyJhbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0" + ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
HEX = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
B64 = "QWxhZGRpbjpvcGVuIHNlc2FtZTEyMzQ1Njc4OTBhYmNkZWZnaGlqa2xtbm9w"


@pytest.mark.parametrize("secret", [GH, GH_PAT, SK, SK_ANT, SLACK, AWS, JWT, HEX, B64])
def test_token_shapes_are_redacted(secret):
    out = redact(f"here it is: {secret} ok")
    assert secret not in out
    # no long fragment of the secret survives either
    assert secret[4:16] not in out
    assert "[REDACTED" in out
    assert out.startswith("here it is: ") and out.endswith(" ok")


@pytest.mark.parametrize("line", [
    "Authorization: Bearer abc.def-ghi_jkl",
    "authorization: Basic dXNlcjpwYXNzd29yZA==",
    "curl -H 'Authorization: token abcdef123456' https://x",
    "Bearer abcdefghijklmnop12345",
])
def test_auth_headers_are_redacted(line):
    out = redact(line)
    for frag in ("abc.def-ghi_jkl", "dXNlcjpwYXNzd29yZA", "abcdef123456", "abcdefghijklmnop12345"):
        assert frag not in out


@pytest.mark.parametrize("line,value", [
    ("API_KEY=supersecretvalue", "supersecretvalue"),
    ("export GITHUB_TOKEN=abc", "abc"),
    ("DB_PASSWORD='hunter2 hunter2'", "hunter2"),
    ('CLIENT_SECRET: "s3cr3t"', "s3cr3t"),
    ("my_api_key = xyz987", "xyz987"),
    ("password=correcthorse", "correcthorse"),
    ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG", "wJalrXUtnFEMI"),
])
def test_key_value_assignments_are_redacted(line, value):
    out = redact(line)
    assert value not in out
    assert "[REDACTED" in out


def test_key_name_is_kept_for_context():
    assert redact("API_KEY=supersecretvalue").startswith("API_KEY=")


def test_private_key_block_is_redacted():
    block = ("-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAA\n"
             "AAAAAAAAAAAAAAAAAAAAAAAA\n-----END OPENSSH PRIVATE KEY-----")
    out = redact(f"key:\n{block}\ndone")
    assert "b3BlbnNzaC1rZXk" not in out
    assert "PRIVATE KEY" not in out or "[REDACTED" in out
    assert out.endswith("done")


def test_truncated_private_key_block_is_redacted_to_end():
    out = redact("-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA1234")
    assert "MIIEpAIBAAKCAQEA" not in out


def test_emails_are_redacted():
    out = redact("mail jane.doe+x@example.co.uk please")
    assert "jane.doe" not in out and "example.co.uk" not in out


@pytest.mark.parametrize("ip", ["10.0.0.5", "192.168.1.20", "172.16.4.1", "172.31.255.255",
                                "100.64.1.2", "169.254.0.9", "10.1.10.0/24", "192.168.50.224:8080"])
def test_private_ipv4_is_redacted(ip):
    out = redact(f"host {ip} up")
    assert ip.split("/")[0].split(":")[0] not in out


def test_public_ipv4_is_also_redacted_when_in_doubt():
    assert "45.76.12.34" not in redact("vps at 45.76.12.34")


def test_url_credentials_and_query_tokens_are_redacted():
    out = redact("https://bob:pa55word@git.example/x?token=abcd1234&page=2")
    assert "pa55word" not in out and "abcd1234" not in out
    assert "page=2" in out


def test_home_directory_is_shortened():
    out = redact("edited /home/alice/projects/app/main.py and /Users/bob/x")
    assert "alice" not in out and "bob" not in out
    assert "~/projects/app/main.py" in out


@pytest.mark.parametrize("text", [
    "please don't edit the generated file, change the source instead",
    "run the tests in tests/test_redact.py and plugins/retro/scripts",
    "use version 1.2.3 of the library",
    "the session id is 4bc5d53d",
    "KEY points: be careful",
])
def test_ordinary_text_is_left_alone(text):
    assert redact(text) == text


def test_redact_is_idempotent():
    once = redact(f"token {GH} and API_KEY=abc and 10.0.0.1")
    assert redact(once) == once


def test_empty_and_none():
    assert redact("") == ""
    assert redact(None) == ""


def test_local_user_name_is_redacted_everywhere(monkeypatch):
    import retro_mine
    monkeypatch.setattr(retro_mine, "_LOCAL_USER", retro_mine._user_pattern("jdoe"))
    out = redact("/tmp/x/-home-jdoe-repo and jdoe@host and jdoes")
    assert "jdoe-" not in out and "jdoe@" not in out
    assert "jdoes" in out  # whole tokens only


def test_short_or_generic_user_names_are_ignored():
    import retro_mine
    assert retro_mine._user_pattern("me") is None
    assert retro_mine._user_pattern("root") is None
