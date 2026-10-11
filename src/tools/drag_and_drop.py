from browser import PlaywrightBrowser, EnvState

from tools.helpers import viewport_pixel_point


def handle_drag_and_drop(computer: PlaywrightBrowser, args: dict) -> EnvState:
    x, y = viewport_pixel_point(args, computer)
    destination_x, destination_y = viewport_pixel_point(
        {"x": args["destination_x"], "y": args["destination_y"]},
        computer,
    )
    return computer.drag_and_drop(
        x=x,
        y=y,
        destination_x=destination_x,
        destination_y=destination_y,
    )
