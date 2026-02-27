from macgent.reasoning.browser_signals import detect_browser_blockers


def test_detects_captcha_signals():
    text = "Please verify you are human. I am not a robot checkbox challenge"
    out = detect_browser_blockers(text, "")
    assert out["is_captcha"] is True
    assert out["captcha_signals"]


def test_detects_antibot_signals():
    text = "Access denied by Cloudflare challenge page"
    out = detect_browser_blockers(text, "")
    assert out["is_antibot"] is True
    assert out["antibot_signals"]


def test_no_signal_on_normal_page():
    text = "Welcome to example.com product catalog"
    out = detect_browser_blockers(text, "")
    assert out["is_captcha"] is False
    assert out["is_antibot"] is False
