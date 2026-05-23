# Part of l10n_it_pdcodm. See LICENSE file for full copyright and licensing details.
# NB: l10n_it_pdcodm_cee_section va PRIMA di account_account perché
# quest'ultimo ha un Many2one computed che lo referenzia.
from . import l10n_it_pdcodm_cee_section
from . import account_account
from . import account_move
from . import account_move_line
from . import res_company
# NB: il prefisso `template_*` è OBBLIGATORIO per la discovery del
# chart template OdooManager (vedi addons/account/models/ir_module.py
# riga 19: `template_module = lambda m: ... m.__name__.startswith('template_')`).
from . import template_l10n_it_pdcodm
