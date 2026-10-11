from browser import PlaywrightBrowser, EnvState

from tools.helpers import viewport_pixel_point


def handle_click_at(computer: PlaywrightBrowser, args: dict) -> EnvState:
    x, y = viewport_pixel_point(args, computer)
    return computer.click_at(x=x, y=y)
