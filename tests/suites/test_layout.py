"""First-pass layout check on the Tier 1 and Tier 2 phone and tablet viewports from the device matrix.

This is emulation: it catches an unreachable button or a sideways scroll, nothing more.
Keyboard, autofill and WebView behavior still need the real devices (see the matrix page).
"""

import pytest

from pages.login_page import LoginPage

DEVICES = [
    pytest.param("iPhone 16 Pro Max", 440, 956, 3, id="iphone-16-pro-max"),
    pytest.param("Galaxy A03s", 360, 800, 2, id="galaxy-a03s"),
    pytest.param("iPhone SE (3rd gen)", 375, 667, 2, id="iphone-se-3"),
    pytest.param("iPad Air 11-inch (M2)", 820, 1180, 2, id="ipad-air-11"),
    pytest.param("iPad mini (6th gen)", 744, 1133, 2, id="ipad-mini-6"),
]


@pytest.mark.smoke
@pytest.mark.parametrize("name,width,height,scale", DEVICES)
def test_checkout_is_usable_on_the_matrix_viewports(context_factory, account, name, width, height, scale):
    context = context_factory(
        viewport={"width": width, "height": height},
        device_scale_factor=scale, is_mobile=True, has_touch=True,
    )
    checkout = LoginPage(context.new_page()).open().sign_in(account).choose_plan()

    assert not checkout.has_horizontal_scroll(), f"{name}: page scrolls sideways"
    assert checkout.confirm_is_unobstructed(), f"{name}: Confirm is outside the viewport or covered"
