import customtkinter as ctk


class _ThemeMeta(type):
    def __getattr__(cls, name):
        if name.startswith("COLOR_"):
            key = name[6:].lower()
            palette = cls._palette()
            if key in palette:
                return palette[key]
        raise AttributeError(f"type object {cls.__name__!r} has no attribute {name!r}")


class _Theme(metaclass=_ThemeMeta):
    WINDOW_SIZE = "960x640"
    WINDOW_MIN_SIZE = (800, 500)
    TOOLBAR_HEIGHT = 60
    STATUS_BAR_HEIGHT = 30
    INFO_FRAME_HEIGHT = 40

    FONT_SIZE_SMALL = 10
    FONT_SIZE_NORMAL = 11
    FONT_SIZE_MEDIUM = 12
    FONT_SIZE_LARGE = 13
    FONT_SIZE_TITLE = 14

    BTN_WIDTH_SMALL = 50
    BTN_WIDTH_MEDIUM = 70
    BTN_WIDTH_NORMAL = 90
    BTN_WIDTH_LARGE = 110

    _LIGHT = {
        "primary": "#2B7DE9",
        "primary_hover": "#1E5DB5",
        "success": "#28A745",
        "success_hover": "#218838",
        "danger": "#DC3545",
        "danger_hover": "#C82333",
        "secondary": "#6C757D",
        "secondary_hover": "#5A6268",
        "warning": "#FFC107",
        "orange": "#FD7E14",
        "text_muted": "gray60",
        "text_subtle": "gray50",
        "bg_card": "#F0F0F0",
        "bg_input": "#FFFFFF",
        "border": "#D0D0D0",
    }

    _DARK = {
        "primary": "#3B8DEE",
        "primary_hover": "#5AA3F5",
        "success": "#34C759",
        "success_hover": "#2DA84E",
        "danger": "#FF453A",
        "danger_hover": "#E03E34",
        "secondary": "#8E8E93",
        "secondary_hover": "#636366",
        "warning": "#FFD60A",
        "orange": "#FF9F0A",
        "text_muted": "gray60",
        "text_subtle": "gray50",
        "bg_card": "#2D2D2D",
        "bg_input": "#1E1E1E",
        "border": "#3A3A3A",
    }

    @classmethod
    def _palette(cls) -> dict:
        mode = ctk.get_appearance_mode()
        return cls._DARK if mode == "Dark" else cls._LIGHT
