from browser import PlaywrightBrowser, EnvState

from tools.helpers import viewport_pixel_point


def handle_hover_at(computer: PlaywrightBrowser, args: dict) -> EnvState:
    x, y = viewport_pixel_point(args, computer)
    return computer.hover_at(x=x, y=y)
