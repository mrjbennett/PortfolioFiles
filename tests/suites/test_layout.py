"""First-pass layout check on the Tier 1 and Tier 2 viewports from the device matrix.

This is emulation: it catches an unreachable button or a sideways scroll, nothing more.
Keyboard, autofill and WebView behavior still need the real devices (see the matrix page).
"""

import pytest

from pages.login_page import LoginPage

DEVICES = [
    pytest.param("iPhone 13", 390, 844, 3, id="iphone-13"),
    pytest.param("Galaxy S23", 360, 780, 3, id="galaxy-s23"),
    pytest.param("Pixel 6a", 412, 915, 2.625, id="pixel-6a"),
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
