"""Persistent preferences (QSettings) and the Settings dialog."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .core import DEFAULT_TEMPLATE, ClipError, ClipRequest

BROWSERS = ["", "chrome", "firefox", "edge", "brave", "opera", "vivaldi", "safari"]

DEFAULTS = {
    "folder": str(Path.home() / "Downloads" / "Clips"),
    "quality": "1080p",
    "video_format": "mp4",
    "audio_format": "mp3",
    "parallel": 2,
    "theme": "system",
    "filename_template": DEFAULT_TEMPLATE,
    "embed_metadata": True,
    "embed_thumbnail": False,
    "rate_limit": "",
    "cookies_browser": "",
    "clipboard_watch": False,
    "notify": True,
    "subtitle_langs": "en",
}


class AppSettings:
    def __init__(self, qsettings: QSettings | None = None):
        self.q = qsettings or QSettings("ChetanGadhiya", "SmartClipDownloader")

    def get(self, key: str):
        default = DEFAULTS[key]
        value = self.q.value(key, default)
        if isinstance(default, bool):
            return value in (True, "true", "1", 1)
        if isinstance(default, int):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        return value if value is not None else default

    def set(self, key: str, value) -> None:
        self.q.setValue(key, value)

    def as_dict(self) -> dict:
        return {k: self.get(k) for k in DEFAULTS}


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        s = settings.as_dict()

        self.folder = QLineEdit(s["folder"])
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        folder_w = QWidget()
        folder_w.setLayout(folder_row)
        folder_row.setContentsMargins(0, 0, 0, 0)

        self.template = QLineEdit(s["filename_template"])
        self.template.setToolTip("yt-dlp output template, e.g. %(uploader)s - %(title)s")
        self.parallel = QSpinBox()
        self.parallel.setRange(1, 5)
        self.parallel.setValue(s["parallel"])
        self.theme = QComboBox()
        self.theme.addItems(["system", "light", "dark"])
        self.theme.setCurrentText(s["theme"])
        self.rate = QLineEdit(s["rate_limit"])
        self.rate.setPlaceholderText("unlimited  (e.g. 2M or 500K)")
        self.cookies = QComboBox()
        self.cookies.addItems([b or "none" for b in BROWSERS])
        self.cookies.setCurrentText(s["cookies_browser"] or "none")
        self.subs = QLineEdit(s["subtitle_langs"])
        self.subs.setToolTip("Comma-separated language codes used when 'Subtitles' is ticked, e.g. en,hi")
        self.meta = QCheckBox("Embed title/artist metadata")
        self.meta.setChecked(s["embed_metadata"])
        self.thumb = QCheckBox("Embed thumbnail as cover art (mp4/mkv/mp3/m4a)")
        self.thumb.setChecked(s["embed_thumbnail"])
        self.clip = QCheckBox("Watch clipboard and offer copied YouTube links")
        self.clip.setChecked(s["clipboard_watch"])
        self.notify = QCheckBox("Desktop notification when downloads finish")
        self.notify.setChecked(s["notify"])
        self.error = QLabel()
        self.error.setObjectName("warning")
        self.error.hide()

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow("Download folder", folder_w)
        form.addRow("File name template", self.template)
        form.addRow("Parallel downloads", self.parallel)
        form.addRow("Theme", self.theme)
        form.addRow("Speed limit", self.rate)
        form.addRow("Cookies from browser", self.cookies)
        form.addRow("Subtitle languages", self.subs)
        hint = QLabel("Cookies let you download age-restricted or members-only videos you can already watch "
                      "in that browser. They never leave your computer.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        for cb in (self.meta, self.thumb, self.clip, self.notify):
            lay.addWidget(cb)
        lay.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._defaults)
        lay.addWidget(buttons)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Download folder", self.folder.text())
        if d:
            self.folder.setText(d)

    def _defaults(self) -> None:
        self.folder.setText(DEFAULTS["folder"])
        self.template.setText(DEFAULTS["filename_template"])
        self.parallel.setValue(DEFAULTS["parallel"])
        self.theme.setCurrentText(DEFAULTS["theme"])
        self.rate.setText("")
        self.cookies.setCurrentText("none")
        self.subs.setText(DEFAULTS["subtitle_langs"])
        self.meta.setChecked(True)
        self.thumb.setChecked(False)
        self.clip.setChecked(False)
        self.notify.setChecked(True)

    def _save(self) -> None:
        cookies = "" if self.cookies.currentText() == "none" else self.cookies.currentText()
        try:  # reuse the core validation for template and rate limit
            ClipRequest("https://youtu.be/x", filename_template=self.template.text() or DEFAULT_TEMPLATE,
                        rate_limit=self.rate.text().strip() or None)
        except ClipError as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        values = {
            "folder": self.folder.text().strip() or DEFAULTS["folder"],
            "filename_template": self.template.text().strip() or DEFAULT_TEMPLATE,
            "parallel": self.parallel.value(),
            "theme": self.theme.currentText(),
            "rate_limit": self.rate.text().strip(),
            "cookies_browser": cookies,
            "subtitle_langs": self.subs.text().strip() or "en",
            "embed_metadata": self.meta.isChecked(),
            "embed_thumbnail": self.thumb.isChecked(),
            "clipboard_watch": self.clip.isChecked(),
            "notify": self.notify.isChecked(),
        }
        for k, v in values.items():
            self.settings.set(k, v)
        self.accept()
