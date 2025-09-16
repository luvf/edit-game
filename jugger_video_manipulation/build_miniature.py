"""Build miniatures for tournaments."""

from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageFilter, ImageFont


class Rescale:
    """Rescale structure. define x, y offset and zoom."""

    def __init__(
        self, *, x_offset: float = 0.0, y_offset: float = 0.0, zoom: float = 1.0
    ):
        """Initialize Rescale object."""
        self.x_offset: Final[float] = x_offset
        self.y_offset: Final[float] = y_offset
        self.zoom: Final[float] = zoom


def get_video_file_names(input_dir: Path) -> list[Path]:
    """Get video files from input dir.

    Args:
        input_dir: dirrectory to search for video files
    Returns:
        list of files names.
    """
    extensions = [".mp4", ".MP4", ".MOV", ".mov", ".mp4", ".avi", ".mkv"]
    return [
        file_name for file_name in input_dir.iterdir() if file_name.suffix in extensions
    ]


def get_text_dimensions(
    text_string: str, font: ImageFont.FreeTypeFont
) -> tuple[int, int]:
    """Get the expected text dimensions.

    Args:
        text_string: text to get dimensions for
        font: font object to use
    Returns:
        dimensions in width and height.
    """
    ascent, descent = font.getmetrics()

    text_width = font.getmask(text_string).getbbox()[2]
    text_height = font.getmask(text_string).getbbox()[3] + descent

    return text_width, text_height


def generate_text_as_image(
    text: str, color: str = "black", text_color: str = "white"
) -> Image.Image:
    """Generate text as an image used to write the tournament name on the miniature.

    Args:
        text: text to generate image from
        color: color of the background
        text_color: color of the text
    Returns:
        image object.
    """
    font = ImageFont.truetype("jugger_video_manipulation/impact.ttf", size=150)
    text = text.upper()
    dimensions = get_text_dimensions(text, font)

    text_image = Image.new("RGBA", (dimensions[0] + 12, dimensions[1] + 8), color=color)
    img_draw = ImageDraw.Draw(text_image)
    img_draw.text((6, 0), text, fill=text_color, font=font)
    return text_image


def rescale_logo(logo: Image.Image) -> Image.Image:
    """Rescale logo to fit the desired size for 1080x1920 image.

    Args:
        logo: logo to rescale
    Returns:
        rescaled logo
    """
    width = 850
    max_height = 850
    logo_width, logo_height = logo.size
    logo = logo.resize((width, int(width * logo_height / logo_width)))
    logo_width, logo_height = logo.size
    if logo_height > max_height:
        logo = logo.resize((int(max_height * logo_width / logo_height), max_height))
    return logo


def paste_image_with_shadow(
    background_image: Image.Image,
    image: Image.Image,
    pos: tuple[int, int],
    shade: float = 10.0,
) -> None:
    """Generate paste an image onto a background image with shadow.

    Args:
        background_image: background image to paste the shadow on
        image: image to shadow on the background
        pos: position of the image on the background.
        shade: we use a gaussian blur, describe the kernel size here.
    """
    x, y = image.size
    rescaled_image = image.resize((int(x * 0.5), int(y * 0.5)))
    shadow_logo = Image.new("RGBA", image.size, (0, 0, 0, 255))
    new_center = (
        x // 2 - rescaled_image.size[0] // 2,
        y // 2 - rescaled_image.size[1] // 2,
    )

    shadow_logo.paste(rescaled_image, new_center, rescaled_image)

    mask = Image.new("L", shadow_logo.size, 0)

    masked = rescaled_image.split()[-1]
    mask.paste(masked, new_center)

    mask_blur = mask.filter(ImageFilter.GaussianBlur(shade))
    mask_blur.paste(masked, new_center, masked)

    background_image.paste(shadow_logo, pos, mask_blur)


def build_team_overlay(
    logo1_rescaled: Image.Image,
    logo2_rescaled: Image.Image,
    background: str | Image.Image,
) -> Image.Image:
    """Build the overlay for the miniature.

    This overlay, is an Image with the team logos and a one color background.

    Args:
        logo1_rescaled: logo of the first team.
        logo2_rescaled: logo of the second team.
        background: color of the background.

    Returns:
        image object.
    """

    def recenter(img: Image.Image, pos: tuple[int, int]) -> tuple[int, int]:
        return pos[0] - int(img.size[0] / 2), pos[1] - int(img.size[1] / 2)

    if isinstance(background, str):
        w, h = 1700, 1500
        rotation = 10
        background_image = Image.new("RGBA", (w, h))
        background_draw = ImageDraw.Draw(background_image)
        background_draw.rectangle([(0, -100), (1000 + w, 101 + h)], fill=background)
        background_image = background_image.rotate(
            rotation, expand=True, resample=Image.Resampling.BICUBIC
        )
    else:
        raise NotImplementedError("background_color must be a string.")

    overlay_image = Image.new("RGBA", (1920, 1080), (250, 250, 250, 0))

    overlay_image.paste(background_image, (-1100, -300))

    logo1_pos = (300, 1080 // 4)
    logo2_pos = (450, 3 * 1080 // 4)

    logo1_rescaled = rescale_logo(logo1_rescaled)
    pos1 = recenter(logo1_rescaled, logo1_pos)
    logo2_rescaled = rescale_logo(logo2_rescaled)
    pos2 = recenter(logo2_rescaled, logo2_pos)

    paste_image_with_shadow(overlay_image, logo1_rescaled, pos1)
    paste_image_with_shadow(overlay_image, logo2_rescaled, pos2)

    return overlay_image


def rescale_image(image: Image.Image, *, rescale: Rescale) -> Image.Image:
    """Rescale an image.

    Args:
        image:source Image
        rescale: rescale object.

    Returns:
        rescaled image
    """
    if rescale.zoom < 1:
        raise ValueError("zoom must be >=1")
    if (
        rescale.x_offset < 0
        or rescale.y_offset < 0
        or rescale.x_offset > 1
        or rescale.y_offset > 1
    ):
        raise ValueError("x_offset and y_offset must be between 0 and 1")

    zoomed_image = image.resize((int(1920 * rescale.zoom), int(1080 * rescale.zoom)))

    zoomed_x_offset = int(rescale.x_offset * (zoomed_image.size[0] + 600 - 1920))
    zoomed_y_offset = int(rescale.y_offset * (zoomed_image.size[1] - 1080))

    return zoomed_image.crop(
        (
            zoomed_x_offset,
            zoomed_y_offset,
            1920 + zoomed_x_offset,
            1080 + zoomed_y_offset,
        )
    )


def assemble_miniature(
    *,
    image: Image.Image,
    overlay: Image.Image,
    tournament_name: Image.Image,
    pos_tournament_name: tuple[int, int],
    rescale: Rescale,
) -> Image.Image:
    """Generate the miniature.

    Args:
        image: frame of the video used a s base
        overlay: overlay image
        tournament_name: tournament name image
        pos_tournament_name: position of the tournament name on the image
        rescale: describes the window of Image to take in the final miature.

    Returns:
        Miniature image.
    """
    miniature_image = Image.new("RGBA", (1920, 1080), (250, 250, 250, 0))
    x, y = image.size
    if x / y > 16 / 9:  # in some situations the source video is not in 16:9 ratio.
        image = image.crop((0, 0, y * 16 / 9, y))
    else:
        image = image.crop((0, 0, x, x * 9 / 16))

    rescaled_image = rescale_image(image=image, rescale=rescale)
    miniature_image.paste(rescaled_image, (600, 0))

    alpha_mask = Image.new("RGBA", image.size, 0)

    ImageDraw.Draw(alpha_mask, "RGBA").rectangle(((0, 0), (1920, 1080)), (0, 0, 0, 40))

    miniature_image.paste(alpha_mask, (0, 0), alpha_mask)

    overlay = overlay.resize((overlay.size[0] * 2, overlay.size[1] * 2))

    paste_image_with_shadow(
        miniature_image,
        overlay,
        (-overlay.size[0] // 4, -overlay.size[1] // 4),
        shade=20,
    )

    paste_image_with_shadow(miniature_image, tournament_name, pos_tournament_name)

    return miniature_image


MINIATURE_DIR = Path("/mnt/video/juggerData/miniatures/team_logos/")


def independent_build_miniature(
    *,
    base_image_name: str,
    team1: str,
    team2: str,
    tournament_name: str,
    tournament_color: str,
    tournament_name_bg_color: str,
    tournament_name_text_color: str,
) -> None:
    """Generate the miniature.

    Args:
        base_image_name: path to the video file
        team1: filename for the first team logo
        team2: filename for the second team logo
        tournament_name: tournament name
        tournament_color: color of the overlay
        tournament_name_bg_color: color of the tournament name background
        tournament_name_text_color: color of the tournament name text
    """
    back_image = Image.open(base_image_name)
    team1_logo = Image.open(MINIATURE_DIR / Path(team1)).convert("RGBA")
    team2_logo = Image.open(MINIATURE_DIR / Path(team2)).convert("RGBA")

    team_overlay = build_team_overlay(
        logo1_rescaled=team1_logo,
        logo2_rescaled=team2_logo,
        background=tournament_color,
    )
    tournament_title = generate_text_as_image(
        tournament_name,
        color=tournament_name_bg_color,
        text_color=tournament_name_text_color,
    )
    pos_tournament_title = 1920 - tournament_title.size[0] * 3 // 4 - 80, 600

    final_image = assemble_miniature(
        image=back_image,
        overlay=team_overlay,
        tournament_name=tournament_title,
        pos_tournament_name=pos_tournament_title,
        rescale=Rescale(),
    ).convert("RGB")
    final_image.show()


def generate_miniature(
    *,
    base_image: Image.Image,
    tournament_name: str,
    tournament_color: str,
    team1: Path,
    team2: Path,
    rescale: Rescale,
) -> Image.Image:
    """Generate the miniature.

    Args:
        base_image: frame of the video used a s base
        tournament_name: tournament name
        tournament_color: color of the overlay
        team1: path for the first team logo
        team2: path for the second team logo
        rescale: describes the window of Image to take in the final miature.

    Returns:
        miniature image.
    """
    team1_logo = Image.open(team1).convert("RGBA")
    team2_logo = Image.open(team2).convert("RGBA")

    team_overlay = build_team_overlay(
        logo1_rescaled=team1_logo,
        logo2_rescaled=team2_logo,
        background=tournament_color,
    )
    tournament_title = generate_text_as_image(
        tournament_name, color="white", text_color="black"
    )
    pos_tournament_title = 1920 - tournament_title.size[0] * 3 // 4 - 80, 600

    return assemble_miniature(
        image=base_image,
        overlay=team_overlay,
        tournament_name=tournament_title,
        pos_tournament_name=pos_tournament_title,
        rescale=rescale,
    ).convert("RGB")
