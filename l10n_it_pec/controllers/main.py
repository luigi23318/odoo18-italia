# -*- coding: utf-8 -*-
# Copyright 2026 OdooManager.cloud
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

from odoo import http, _
from odoo.http import request, Response
from odoo.exceptions import UserError, AccessError


class L10nItPecController(http.Controller):
    """Controller per servire l'anteprima XML FatturaPA direttamente via HTTP,
    senza creare ir.attachment temporanei nel DB.
    """

    @http.route(
        '/l10n_it_pec/preview_xml/<int:move_id>',
        type='http',
        auth='user',
        methods=['GET'],
    )
    def preview_xml(self, move_id, **kwargs):
        """Restituisce l'XML FatturaPA della fattura come risposta HTTP.

        Strategia di ricerca:
        1. Usa l10n_it_edi_attachment_id (campo standard Odoo)
        2. Usa l10n_it_pec_xml_attachment_id (campo modulo PEC)
        3. Cerca tra binary fields (Odoo 18 li nasconde dal search standard)
        4. Genera XML in memoria al volo e lo serve

        In nessun caso viene creato un ir.attachment.
        """
        move = request.env['account.move'].browse(move_id)
        try:
            move.check_access_rights('read')
            move.check_access_rule('read')
        except AccessError:
            return request.not_found()

        if not move.exists():
            return request.not_found()

        if move.state != 'posted':
            return Response(
                _("La fattura deve essere confermata per generare l'XML."),
                status=400,
                content_type='text/plain; charset=utf-8',
            )

        # 1-2. Campi standard
        attachment = move.l10n_it_edi_attachment_id or move.l10n_it_pec_xml_attachment_id

        # 3. Binary fields
        if not attachment:
            attachment = request.env['ir.attachment'].sudo().search([
                ('res_model', '=', 'account.move'),
                ('res_id', '=', move.id),
                ('res_field', '=', 'l10n_it_edi_attachment_file'),
            ], limit=1, order='create_date desc')

        if attachment:
            xml_content = attachment.raw
            filename = attachment.name or f'fattura_{move.id}.xml'
        else:
            # 4. Genera al volo in memoria
            errors = move._l10n_it_edi_export_data_check()
            if errors:
                messages = [error_data['message'] for error_data in errors.values()]
                return Response(
                    '\n'.join(messages),
                    status=400,
                    content_type='text/plain; charset=utf-8',
                )
            xml_content = move._l10n_it_edi_render_xml()
            filename = f'anteprima_{(move.name or str(move.id)).replace("/", "_")}.xml'

        # Servi l'XML come risposta inline (visualizzazione nel browser)
        return Response(
            xml_content,
            headers=[
                ('Content-Type', 'application/xml; charset=utf-8'),
                ('Content-Disposition', f'inline; filename="{filename}"'),
            ],
        )
