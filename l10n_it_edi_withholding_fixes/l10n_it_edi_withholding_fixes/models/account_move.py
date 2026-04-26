# -*- coding: utf-8 -*-
"""Fix per bug noti del modulo l10n_it_edi_withholding (Odoo S.A.).

Questo modulo replica concettualmente la funzione storica del modulo
OCA ``l10n_it_fatturapa_out_wt`` (versioni 8.0-16.0), correggendo bug
della generazione XML FatturaPA quando sono presenti ritenute d'acconto
o contributi assimilati a ritenute (es. ENASARCO TC07).

Tutti i fix sono progettati per essere auto-disattivanti: intervengono
solo se rilevano una discrepanza effettiva tra valore calcolato e
valore atteso. Quando Odoo S.A. correggerà i bug upstream, i fix
smetteranno automaticamente di intervenire.
"""

import logging

from odoo import models

_logger = logging.getLogger(__name__)

# Soglia minima di discrepanza (in valuta) sopra la quale il fix interviene.
# Sotto questa soglia consideriamo il valore corretto entro l'errore di
# arrotondamento e non interveniamo.
DISCREPANCY_THRESHOLD = 0.01

# Codice TC07 identifica l'ENASARCO. Per le specifiche FatturaPA e le FAQ
# dell'Agenzia Entrate, l'ENASARCO è classificato come "cassa previdenziale"
# ma viene gestito come ritenuta (RT04) nel XML, e NON deve essere incluso
# nel calcolo di ImportoTotaleDocumento (è una trattenuta, non un'aggiunta
# all'imponibile).
ENASARCO_PENSION_FUND_TYPE = 'TC07'


class AccountMove(models.Model):
    _inherit = 'account.move'

    # ------------------------------------------------------------------
    # Hook principale: orchestrazione di tutti i fix
    # ------------------------------------------------------------------

    def _l10n_it_edi_get_values(self, pdf_values=None):
        """Override del metodo principale di generazione valori EDI.

        Chiama il super() del modulo standard, poi applica in sequenza
        tutti i fix conosciuti. Ogni fix valuta autonomamente se
        intervenire.
        """
        values = super()._l10n_it_edi_get_values(pdf_values)

        # Fix #1: ImportoTotaleDocumento errato in presenza di ritenute
        values = self._l10n_it_edi_fix_importo_totale_documento(values)

        # Spazio per fix futuri:
        # values = self._l10n_it_edi_fix_xxx(values)

        return values

    # ------------------------------------------------------------------
    # Helper: classificazione tax e calcolo lordo
    # ------------------------------------------------------------------

    def _l10n_it_edi_has_withholding_or_enasarco(self):
        """Verifica se la fattura ha almeno una ritenuta o ENASARCO.

        La verifica si basa sulla classificazione delle tax via
        ``_l10n_it_filter_kind``. ENASARCO viene rilevato anche quando
        è classificato solo come pension_fund TC07 (caso reale rilevato
        nel modulo Odoo 18 ``l10n_it_edi_withholding``).

        :return: True se ci sono ritenute o ENASARCO, False altrimenti
        """
        self.ensure_one()
        for line in self.invoice_line_ids:
            for tax in line.tax_ids:
                # Caso 1: tax classificata come withholding (RT01-RT06)
                if tax._l10n_it_filter_kind('withholding'):
                    return True
                # Caso 2: tax classificata come pension_fund TC07 (ENASARCO)
                # Anche se non è withholding nel filter_kind, va trattata
                # come tale per il calcolo del totale documento.
                if tax._l10n_it_filter_kind('pension_fund'):
                    if getattr(tax, 'l10n_it_pension_fund_type', None) == ENASARCO_PENSION_FUND_TYPE:
                        return True
        return False

    def _l10n_it_edi_compute_real_pension_fund(self):
        """Calcola l'importo della cassa previdenziale "vera".

        Per "vera" si intende: cassa previdenziale TC01-TC22 escluso
        TC07 (ENASARCO). La cassa previdenziale vera contribuisce
        positivamente al lordo del documento (al contrario di ENASARCO
        che è trattenuto).

        Esempio: avvocato con cassa forense TC02 4% su imponibile 1000.
        La cassa è 40€ e va inclusa nel lordo (1000+40=1040 base IVA).

        :return: importo della cassa previdenziale vera (positivo se
                 contribuisce al lordo, normalmente è positivo)
        """
        self.ensure_one()
        total = 0.0
        for line in self.invoice_line_ids:
            for tax in line.tax_ids:
                if not tax._l10n_it_filter_kind('pension_fund'):
                    continue
                pf_type = getattr(tax, 'l10n_it_pension_fund_type', None)
                if pf_type == ENASARCO_PENSION_FUND_TYPE:
                    # Escludiamo ENASARCO: non contribuisce al lordo,
                    # è una trattenuta come le ritenute.
                    continue
                # Cassa previdenziale vera: contribuisce al lordo.
                # Calcoliamo l'importo come percentuale dell'imponibile
                # della riga.
                if tax.amount_type == 'percent':
                    total += line.price_subtotal * tax.amount / 100.0
                elif tax.amount_type == 'fixed':
                    total += tax.amount * line.quantity
                # Altri amount_type sono rari per casse previdenziali,
                # li ignoriamo.
        return total

    def _l10n_it_edi_compute_expected_total_document(self):
        """Calcola il valore atteso di ImportoTotaleDocumento.

        Secondo la specifica FatturaPA 1.6.1 e le FAQ dell'Agenzia
        Entrate, ImportoTotaleDocumento deve essere il LORDO del
        documento, calcolato come::

            LORDO = Imponibile + IVA + Cassa Previdenziale "vera"

        Dove "vera" esclude ENASARCO (TC07) che è trattenuto come
        una ritenuta.

        Le ritenute (RT01-RT06) NON sono mai incluse: ImportoTotaleDocumento
        rappresenta il lordo PRIMA della trattenuta, non il netto pagato.

        :return: importo lordo atteso
        """
        self.ensure_one()
        return (
            self.amount_untaxed_signed
            + self.l10n_it_amount_vat_signed
            + self._l10n_it_edi_compute_real_pension_fund()
        )

    # ------------------------------------------------------------------
    # Fix #1: ImportoTotaleDocumento con ritenute
    # ------------------------------------------------------------------

    def _l10n_it_edi_fix_importo_totale_documento(self, values):
        """Corregge ImportoTotaleDocumento quando ci sono ritenute o ENASARCO.

        Bug: il modulo l10n_it_edi_withholding di Odoo S.A. genera
        ``importo_totale_documento`` usando ``amount_total`` (netto
        ritenute), ma la specifica FatturaPA 1.6.1 richiede il lordo.

        Anche il campo ``l10n_it_amount_before_withholding_signed``
        del modulo standard è buggato per il caso ENASARCO TC07:
        include ENASARCO come pension_fund e quindi sottrae il valore
        invece di lasciarlo fuori. Per questo il fix calcola il lordo
        in autonomia.

        Esempi normativi:

        1. Agente forfettario:
            - Provvigione: 1000.00
            - IVA 0% N2.2: 0.00
            - ENASARCO -8.5%: -85.00
            - amount_total: 915.00 (netto)
            - Lordo atteso: 1000.00

        2. Agente ordinario:
            - Provvigione: 1000.00
            - IVA 22%: 220.00
            - ENASARCO -8.5%: -85.00
            - Ritenuta IRPEF 23% su 50%: -115.00
            - amount_total: 1020.00 (netto)
            - Lordo atteso: 1220.00

        3. Avvocato con cassa TC02:
            - Onorario: 1000.00
            - Cassa TC02 4%: 40.00
            - IVA 22% su 1040: 228.80
            - Ritenuta IRPEF 20%: -200.00
            - amount_total: 1068.80 (netto)
            - Lordo atteso: 1268.80

        Strategia del fix:
            1. Verifica presenza ritenute/ENASARCO sulla fattura
            2. Calcola autonomamente il lordo atteso
            3. Confronta con valore calcolato dal super()
            4. Se discrepanza > soglia, sovrascrive con il valore corretto

        Auto-disattivazione:
            Se Odoo S.A. correggerà il bug upstream, il super()
            calcolerà già il valore corretto, la discrepanza sarà nulla,
            e il fix non modificherà nulla.

        :param values: dict di valori per il template XML
        :return: dict eventualmente con ``importo_totale_documento`` corretto
        """
        self.ensure_one()

        # Step 1: verifica se ci sono ritenute o ENASARCO sulla fattura.
        # Se non ce ne sono, il fix non si applica.
        if not self._l10n_it_edi_has_withholding_or_enasarco():
            return values

        # Step 2: calcola autonomamente il valore atteso (lordo).
        # Non ci affidiamo a l10n_it_amount_before_withholding_signed
        # perché è buggato per il caso ENASARCO.
        expected_total = self._l10n_it_edi_compute_expected_total_document()

        # Step 3: recupera il valore calcolato dal super() per confronto.
        computed_total = values.get('importo_totale_documento')
        if computed_total is None:
            _logger.warning(
                "Fix ImportoTotaleDocumento NON applicato a %s: "
                "il super() non ha popolato 'importo_totale_documento'.",
                self.display_name,
            )
            return values

        # Step 4: confronto e intervento condizionale.
        discrepancy = abs(computed_total - expected_total)

        if discrepancy < DISCREPANCY_THRESHOLD:
            # Nessuna discrepanza significativa: il bug non si manifesta.
            _logger.info(
                "Fix ImportoTotaleDocumento NON necessario per %s: "
                "computed=%.2f, expected=%.2f, discrepancy=%.4f (< %.2f). "
                "Il modulo upstream sembra funzionare correttamente.",
                self.display_name,
                computed_total,
                expected_total,
                discrepancy,
                DISCREPANCY_THRESHOLD,
            )
            return values

        # Discrepanza significativa: applichiamo il fix.
        _logger.info(
            "Fix ImportoTotaleDocumento APPLICATO a %s: "
            "computed=%.2f -> expected=%.2f (discrepancy=%.2f). "
            "Causa: bug noto di l10n_it_edi_withholding con fatture "
            "con ritenute o ENASARCO TC07.",
            self.display_name,
            computed_total,
            expected_total,
            discrepancy,
        )
        values['importo_totale_documento'] = expected_total

        return values
