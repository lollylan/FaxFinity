"""Testpaket.

Die Verarbeitungskette protokolliert erwartete Fehlerfälle über logging.
Beim Testen wird das stummgeschaltet, damit Fehlschläge nicht in
Traceback-Ausgaben untergehen, die zum erwarteten Verhalten gehören.
"""

import logging

logging.disable(logging.CRITICAL)
