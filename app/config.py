import configparser

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INI_PATH = PROJECT_ROOT / "config.ini"


def _load_ini() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    if INI_PATH.exists():
        parser.read(INI_PATH)
    return parser


_ini = _load_ini()


class Config:
    JSON_SORT_KEYS = False

    UPLOAD_DIR = PROJECT_ROOT / _ini.get("data", "upload_folder", fallback="uploads")
    MAX_UPLOAD_MB = _ini.getint("data", "max_upload_mb", fallback=25)

    # Default parameters, used to pre-fill the form
    K_E = _ini.getfloat("defaults", "k_e", fallback=2.0)
    K_P = _ini.getfloat("defaults", "k_p", fallback=1.0)
    N_P = _ini.getint("defaults", "n_p", fallback=3)
    N_M = _ini.getint("defaults", "n_m", fallback=7)
    K_M = _ini.getfloat("defaults", "k_m", fallback=1.2)
    N_EXIT = _ini.getint("defaults", "n_exit", fallback=1)
    WINDOW = _ini.getint("defaults", "window", fallback=20)
    EWMA_ALPHA = _ini.getfloat("defaults", "ewma_alpha", fallback=0.3)
    PERCENTILE_P = _ini.getfloat("defaults", "percentile_p", fallback=0.01)
    K_IQR = _ini.getfloat("defaults", "k_iqr", fallback=1.5)

    ROC_WINDOW = _ini.getint("defaults", "roc_window", fallback=1)
    ROC_BASELINE_WINDOW = _ini.getint("defaults", "roc_baseline_window", fallback=20)
    ROC_K = _ini.getfloat("defaults", "roc_k", fallback=2.0)
    FREQUENCY_WINDOW = _ini.getint("defaults", "frequency_window", fallback=10)
    FREQUENCY_MIN_COUNT = _ini.getint("defaults", "frequency_min_count", fallback=2)

    W_MAGNITUDE = _ini.getfloat("defaults", "w_magnitude", fallback=0.4)
    W_DURATION = _ini.getfloat("defaults", "w_duration", fallback=0.4)
    W_FREQUENCY = _ini.getfloat("defaults", "w_frequency", fallback=0.2)

    HOST = _ini.get("app", "host", fallback="127.0.0.1")
    PORT = _ini.getint("app", "port", fallback=5100)
    DEBUG = _ini.getboolean("app", "debug", fallback=False)
