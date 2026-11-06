# SPDX-License-Identifier: GPL-3.0-only
"""Bolha nativa: versão do código e versão do pacote instalado."""
import json
from pathlib import Path
import re
import sys

VERSION = '0.4.3'
if getattr(sys, 'frozen', False):
    value = json.loads((Path(sys._MEIPASS) / 'bolha-version.json').read_text(encoding='utf-8'))
    if not isinstance(value, dict) or not re.fullmatch(r'\d+\.\d+\.\d+', str(value.get('version', ''))):
        raise RuntimeError('Versão do pacote Bolha inválida.')
    VERSION = value['version']
