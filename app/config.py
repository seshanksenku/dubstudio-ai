import os
from pathlib import Path
DATA = Path(os.getenv('DATA_DIR', '/data')).resolve()
LANGUAGES = {
    'en': ('English', 'eng_Latn', 'eng'),
    'hi': ('Hindi', 'hin_Deva', 'hin'),
    'te': ('Telugu', 'tel_Telu', 'tel'),
    'ta': ('Tamil', 'tam_Taml', 'tam'),
    'es': ('Spanish', 'spa_Latn', 'spa'),
    'fr': ('French', 'fra_Latn', 'fra'),
    'de': ('German', 'deu_Latn', 'deu'),
}
