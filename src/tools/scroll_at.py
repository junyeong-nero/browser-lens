from browser import PlaywrightBrowser, EnvState

from tools.helpers import viewport_pixel_point, viewport_pixel_scroll_magnitude


def handle_scroll_at(computer: PlaywrightBrowser, args: dict) -> EnvState:
    direction = args["direction"]
    magnitude = viewport_pixel_scroll_magnitude(
        direction,
        args.get("magnitude", 800),
        computer,
    )
    x, y = viewport_pixel_point(args, computer)

    return computer.scroll_at(
        x=x,
        y=y,
        direction=direction,
        magnitude=magnitude,
    )
