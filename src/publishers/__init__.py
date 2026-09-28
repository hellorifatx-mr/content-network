from . import facebook, instagram, pinterest, tiktok, youtube

REGISTRY = {
    "facebook": facebook,
    "instagram": instagram,
    "pinterest": pinterest,
    "tiktok": tiktok,
    "youtube": youtube,
}


def get(platform):
    mod = REGISTRY.get(platform)
    if not mod:
        raise KeyError(f"no publisher module for platform '{platform}'")
    return mod
