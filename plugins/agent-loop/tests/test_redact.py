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
    "run the tests in tests/test_redact.py and src/app/scripts",
    "mkdir -p build/out && git push -u origin main",
    "docker run -u 1000:1000 image",
    "see npm_config_cache and the pypi-packaging-guide page",
    "pwsh: command not found",
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


# Secrets glued to "_" or other word characters, and short tokens with known prefixes.
GLPAT = "glpat-" + "AbCdEfGhIjKlMnOpQrSt"
NPM = "npm_" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn"
PYPI = "pypi-" + "AgEIcHlwaS5vcmcCJ"
HF = "hf_" + "AbCdEfGhIjKlMnOpQr12"
XOXP = "xoxp-" + "1234567890-AbCdEf"
GHS_SHORT = "ghs_" + "Ab1Cd2Ef3Gh4Ij5K"


@pytest.mark.parametrize("text,secret", [
    ("host_192.168.1.5", "192.168.1.5"),
    ("db_10.0.0.5", "10.0.0.5"),
    ("10.0.0.5_db", "10.0.0.5"),
    ("x_ghp_" + "a" * 28, "a" * 28),
    ("foo_" + "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdef", "eyJzdWIiOiIxIn0"),
    ("curl -u admin:hunter2secret https://x", "hunter2secret"),
    ("curl --user=admin:hunter2secret https://x", "hunter2secret"),
    ("mysql --password hunter2secret -h db", "hunter2secret"),
    ("mysql -u root -p hunter2secret mydb", "hunter2secret"),
    ("mysqldump -phunter2secret mydb", "hunter2secret"),
    ("sshpass -p hunter2secret ssh x", "hunter2secret"),
    ("tool --token hunter2secret", "hunter2secret"),
    ("pw:hunter2", "hunter2"),
    ("pw = hunter2", "hunter2"),
    ("pwd=hunter2", "hunter2"),
    ("passwd: hunter2", "hunter2"),
    ("token " + GLPAT, GLPAT[6:]),
    ("token " + NPM, NPM[4:]),
    ("token " + PYPI, PYPI[5:]),
    ("token " + HF, HF[3:]),
    ("token " + XOXP, XOXP[5:]),
    ("token " + GHS_SHORT, GHS_SHORT[4:]),
    ("x_" + GLPAT, GLPAT[6:]),
])
def test_glued_and_prefixed_secrets_are_redacted(text, secret):
    out = redact(text)
    assert secret not in out, out
    assert "[REDACTED" in out
    assert redact(out) == out


# --- Fix round 3: linear-time redaction, -u/quoted leaks, keyword over-redaction.

import time

from retro_mine import REDACT_MAX, _redact_all

_N = 200_000
ADVERSARIAL = {
    "dot-dash": "ab.cd-" * (_N // 6),
    "x-dot": "x." * (_N // 2),
    "a-underscore": "a_" * (_N // 2),
    "digit-dot": "1." * (_N // 2),
    "ip-ish": "1.1.1." * (_N // 6),
    "base64-ish": "aB3+/" * (_N // 5),
    "base64-run": "aB3" * (_N // 3) + "!",
    "equals": "=" * _N,
    "colons": ":" * _N,
    "a-colon": "a:" * (_N // 2),
    "kv-chain": "a=" * (_N // 2),
    "key-chain": "key=" * (_N // 4),
    "jwt-ish": "eyJaaaaa." * (_N // 9),
    "email-ish": "a%" * (_N // 2),
    "email-domain": "a@" + "b." * (_N // 2),
    "mysql-words": "mysql " * (_N // 6),
    "url-ish": "x://" + "b:" * (_N // 2),
    "spaces": "a" + " " * _N,
}


@pytest.mark.parametrize("name", sorted(ADVERSARIAL))
def test_redaction_is_linear_on_adversarial_input(name):
    text = ADVERSARIAL[name]
    start = time.perf_counter()
    _redact_all(text)  # uncapped: proves every pattern itself is linear
    assert time.perf_counter() - start < 1.0, name


def test_summarize_tool_on_long_identifier_run_is_fast():
    from retro_mine import summarize_tool
    start = time.perf_counter()
    summarize_tool({"name": "Bash", "input": {"command": "echo " + "ab.cd-" * 6666}})
    assert time.perf_counter() - start < 1.0


def test_redact_caps_its_input():
    out = redact("word " * (REDACT_MAX // 2))
    assert len(out) <= REDACT_MAX + 20


def test_cap_without_whitespace_drops_the_cut_token():
    out = redact("a," * ((REDACT_MAX - 10) // 2) + GH)
    assert "ghp_" not in out and "A1b2" not in out


def test_cap_never_leaves_a_fragment_of_a_cut_secret():
    pad = "x " * ((REDACT_MAX - 10) // 2)
    for tail in (GH, "API_KEY=" + "s3cretvalue" * 3, "--password 'hunter2 hunter2 hunter2'"):
        out = redact(pad + tail)
        assert "A1b2C3" not in out and "s3cret" not in out and "hunter2" not in out, tail


@pytest.mark.parametrize("text,secret", [
    ("curl -ualice:s3cret x", "s3cret"),
    ("curl -u 'alice:s3cr et' x", "et"),
    ('curl -u "alice:s3cr et" x', "et"),
    ("curl --user='alice:s3cr et' x", "et"),
    ("tool --password 's3cr et' x", "et"),
    ('tool --token="s3cr et" x', "et"),
    ("tool --password 's3cr et", "et"),
    ("API_KEY='s3cr et", "et"),
])
def test_glued_and_quoted_command_line_credentials_are_redacted(text, secret):
    out = redact(text)
    assert "s3cr" not in out and " " + secret not in out, out
    assert "[REDACTED" in out


@pytest.mark.parametrize("text", [
    "monkey: banana",
    "The keyboard: broken",
    "Hotkey: ctrl+k",
    "turkey=1",
    "keyring: gnome",
    "tokenizer: bpe",
])
def test_keyword_inside_a_word_is_left_alone(text):
    assert redact(text) == text


@pytest.mark.parametrize("line,value", [
    ("apiKey: abc123", "abc123"),
    ("api-key: abc123", "abc123"),
    ("secret_key=abc123", "abc123"),
    ("x-api-key: abc123", "abc123"),
    ("GITHUBTOKEN=abc123", "abc123"),
    ("sessionId=abc123", "abc123"),
    ("session_id: abc123", "abc123"),
    ("passwords=abc123", "abc123"),
    ('{"token":"abc123"}', "abc123"),
    ("docker run --env=API_KEY=abc123", "abc123"),
    ("foo=token=abc123", "abc123"),
    ("key: abc123", "abc123"),
])
def test_keyword_components_are_still_redacted(line, value):
    out = redact(line)
    assert value not in out, out
    assert "[REDACTED" in out
    assert redact(out) == out
