import os
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from .models import Lancamento
from .services import inicializar_estrutura_padrao_usuario
from .extrato_parser import importar_extrato_pdf, importar_extrato_csv, importar_extrato_ofx, processar_importacao_extrato
from .forms import ImportarExtratoForm


class HealthAndLoginSmokeTests(TestCase):
    def test_healthz_endpoint_returns_ok(self):
        response = self.client.get(reverse('healthz'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_login_page_loads(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)


class ExtratoParserAndSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='123')
        inicializar_estrutura_padrao_usuario(self.user, recebe_duas_datas=True, salario=Decimal('4500.00'))

    def test_importar_extrato_banco_inter_pdf_real(self):
        caminho_pdf = '/home/zurc/Downloads/Extrato-05-11-2026-a-22-11-2026-PDF.pdf'
        if not os.path.exists(caminho_pdf):
            self.skipTest('PDF de exemplo não encontrado em /home/zurc/Downloads')

        with open(caminho_pdf, 'rb') as f:
            resultado = importar_extrato_pdf(self.user, f, evitar_duplicados=True)

        self.assertEqual(resultado['criados'], 39)
        self.assertEqual(resultado['ignorados'], 0)

        # Verifica se segunda importação ignora duplicados
        with open(caminho_pdf, 'rb') as f:
            resultado_dup = importar_extrato_pdf(self.user, f, evitar_duplicados=True)
        self.assertEqual(resultado_dup['criados'], 0)
        self.assertEqual(resultado_dup['ignorados'], 39)

        # Verifica detecção de formas de pagamento
        self.assertTrue(Lancamento.objects.filter(usuario=self.user, forma_pagamento=Lancamento.FORMA_PIX).exists())
        self.assertTrue(Lancamento.objects.filter(usuario=self.user, forma_pagamento=Lancamento.FORMA_DEBITO).exists())
        self.assertTrue(Lancamento.objects.filter(usuario=self.user, forma_pagamento=Lancamento.FORMA_BOLETO).exists())
        self.assertTrue(Lancamento.objects.filter(usuario=self.user, forma_pagamento=Lancamento.FORMA_TRANSFERENCIA).exists())

    def test_rejeita_arquivo_pdf_falso_magic_bytes(self):
        falso_pdf = SimpleUploadedFile('extrato.pdf', b'ISTO_NAO_E_UM_PDF', content_type='application/pdf')
        form = ImportarExtratoForm(
            data={'banco': ImportarExtratoForm.BANCO_INTER, 'evitar_duplicados': True},
            files={'arquivo': falso_pdf}
        )
        self.assertFalse(form.is_valid())
        self.assertIn('arquivo', form.errors)

    def test_importar_extrato_csv(self):
        conteudo_csv = (
            "Data,Valor,Identificador,Descrição\n"
            "05/11/2026,-45.90,123,Compra no debito - Padaria Central\n"
            "20/11/2026,2500.00,124,Salario recebido via Pix\n"
        ).encode('utf-8')
        arq_csv = SimpleUploadedFile('nubank.csv', conteudo_csv, content_type='text/csv')
        res = importar_extrato_csv(self.user, arq_csv, banco_selecionado='NUBANK', evitar_duplicados=True)
        self.assertEqual(res['criados'], 2)

    def test_importar_extrato_ofx_universal(self):
        conteudo_ofx = (
            b"OFXHEADER:100\n<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>"
            b"<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261110<TRNAMT>-120.50<MEMO>COMPRA CARTAO DEBITO SUPERMERCADO</STMTTRN>"
            b"<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261120<TRNAMT>3400.00<MEMO>CREDITO SALARIO FOLHA</STMTTRN>"
            b"</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"
        )
        arq_ofx = SimpleUploadedFile('itau.ofx', conteudo_ofx, content_type='application/x-ofx')
        res = processar_importacao_extrato(self.user, banco='ITAU', arquivo=arq_ofx, evitar_duplicados=True)
        self.assertEqual(res['criados'], 2)
