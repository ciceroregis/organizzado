import csv
import io
import os
import re
import datetime
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from django.db import transaction
from pypdf import PdfReader

from .models import Categoria, Lancamento
from .meses_pt import MESES_PT

NOMES_BANCOS = {
    'AUTO': 'Detecção Automática',
    'INTER': 'Banco Inter',
    'NUBANK': 'Nubank',
    'ITAU': 'Itaú',
    'BRADESCO': 'Bradesco',
    'SANTANDER': 'Santander',
    'CAIXA': 'Caixa Econômica Federal',
    'BB': 'Banco do Brasil',
    'C6': 'C6 Bank',
    'SICOOB': 'Sicoob / Sicredi',
    'OUTRO': 'Outro Banco / Instituição',
}

REGEX_DATA_EXTENSO = re.compile(
    r'(\d{1,2})\s+de\s+([A-Za-zçÇ]+?)(?:\s+de\s+(\d{4}))?(?:\s+Saldo|\s*$)',
    re.IGNORECASE
)

REGEX_TX_ASPAS = re.compile(
    r'^(Pix enviado|Pix recebido|Compra no debito|Compra no credito|Pagamento de Titulo|'
    r'Pagamento efetuado|Transferencia|TED|DOC|Salario\s+recebido(?:\s*-\s*Portabilidade)?):\s*'
    r'"([^"]+)"\s+(-?R\$\s*[\d\.,]+)(?:\s+(-?R\$\s*[\d\.,]+))?',
    re.IGNORECASE
)

REGEX_TX_LINHA_DATA = re.compile(
    r'^(?P<data>\d{2}/\d{2}(?:/\d{2,4})?|\d{4}-\d{2}-\d{2})\s+'
    r'(?P<descricao>.+?)\s+'
    r'(?P<sinal_ant>[-+])?\s*(?:R\$\s*)?(?P<valor>\d{1,3}(?:\.\d{3})*,\d{2}|\d+\.\d{2})\s*'
    r'(?P<sinal_pos>[-+CDcd])?'
    r'(?:\s+(?:R\$\s*)?[-+]?\d{1,3}(?:\.\d{3})*,\d{2}\s*[-+CDcd]?)?$'
)

REGEX_TX_SEM_DATA_NA_LINHA = re.compile(
    r'^(?P<descricao>[A-Za-zÀ-ÿ0-9].{3,110}?)\s+'
    r'(?P<sinal_ant>[-+])?\s*R\$\s*(?P<valor>\d{1,3}(?:\.\d{3})*,\d{2})\s*'
    r'(?P<sinal_pos>[-+CDcd])?'
    r'(?:\s+-?R\$\s*\d{1,3}(?:\.\d{3})*,\d{2})?$'
)

TERMOS_IGNORADOS_EXTRATO = (
    'SALDO DO DIA', 'SALDO ANTERIOR', 'SALDO TOTAL', 'SALDO DISPONIVEL', 'SALDO DISPONÍVEL',
    'SALDO BLOQUEADO', 'SALDO FINAL', 'SALDO EM CONTA', 'TOTAL DO DIA', 'LIMITE DISPONIVEL',
    'SAC:', 'OUVIDORIA:', 'FALE COM A GENTE', 'EXTRATO DE CONTA', 'SOLICITADO EM',
)

PALAVRAS_RECEITA = (
    'PIX RECEBIDO', 'RECEBIDO', 'SALARIO', 'SALÁRIO', 'PORTABILIDADE',
    'CREDITO EM CONTA', 'CRÉDITO EM CONTA', 'RENDIMENTO', 'DIVIDENDO',
    'ESTORNO', 'REEMBOLSO', 'DEPOSITO', 'DEPÓSITO', 'REMUNERACAO',
)

PALAVRAS_DESPESA = (
    'PIX ENVIADO', 'ENVIADO', 'COMPRA', 'PAGAMENTO', 'DEBITO', 'DÉBITO',
    'TARIFA', 'IOF', 'SAQUE', 'BOLETO', 'FATURA', 'ENVIO',
)

MAPA_CATEGORIAS_DESPESA = {
    'Moradia': ['ALUGUEL', 'CONDOMINIO', 'ENERGIA', 'ENEL', 'CEMIG', 'COPEL', 'SABESP', 'SANEAGO', 'AGUA', 'INTERNET', 'CLARO', 'VIVO', 'TIM', 'OI'],
    'Deslocamento': ['POSTO', 'PETRONORTE', 'IPIRANGA', 'SHELL', 'BRASILSAT', 'GPS', 'UBER', '99', 'COMBUSTIVEL', 'PEDAGIO', 'SEM PARAR', 'VELOE'],
    'Lazer': ['NETFLIX', 'GOOGLE', 'SPOTIFY', 'CINEMA', 'PRIME', 'DISNEY', 'HBO', 'STEAM', 'PLAYSTATION', 'XBOX'],
    'Vestuário': ['RENNER', 'RIACHUELO', 'CEA', 'CENTAURO', 'ZARA', 'SHEIN', 'NIKE'],
    'Despesas Financeiras': ['NU PAGAMENTOS', 'REALIZE', 'CREDITO', 'ANTPAY', 'FATURA', 'TARIFA', 'IOF', 'ANUIDADE', 'EMPRESTIMO'],
    'Alimentação': ['SUPERMERCADO', 'ATACADISTA', 'ASSAI', 'CARREFOUR', 'PAO DE ACUCAR', 'IFOOD', 'PADARIA', 'MERCADO', 'RESTAURANTE', 'LANCHONETE', 'ACAI', 'ACOUGUE'],
    'Saúde': ['FARMACIA', 'DROGARIA', 'DROGASIL', 'PAGUE MENOS', 'HOSPITAL', 'CLINICA', 'UNIMED', 'AMIL', 'HAPVIDA', 'LABORATORIO'],
    'Educação': ['FACULDADE', 'ESCOLA', 'CURSO', 'UDEMY', 'ALURA', 'LIVRARIA'],
}


@dataclass
class TransacaoExtraida:
    data: datetime.date
    descricao_limpa: str
    texto_bruto: str
    valor: Decimal
    eh_receita: bool


def _decodificar_bytes(conteudo_bytes: bytes) -> str:
    for encoding in ('utf-8-sig', 'latin-1'):
        try:
            return conteudo_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return conteudo_bytes.decode('utf-8', errors='ignore')


def _eh_linha_ignorada(texto: str) -> bool:
    texto_up = texto.upper()
    return any(termo in texto_up for termo in TERMOS_IGNORADOS_EXTRATO)


def _limpar_descricao(tipo_ou_texto: str, detalhe: str = '') -> str:
    combinado = f"{tipo_ou_texto.strip()}: {detalhe.strip()}" if detalhe else tipo_ou_texto.strip()
    limpo = re.sub(r'Cp\s*:\d+-', '', combinado, flags=re.IGNORECASE)
    limpo = re.sub(r'No estabelecimento\s+', '', limpo, flags=re.IGNORECASE)
    limpo = re.sub(r'\s+', ' ', limpo).strip(' :-')
    return (limpo or 'Transação Bancária')[:140]


def _detectar_forma_pagamento(texto_transacao: str) -> str:
    t = texto_transacao.lower()
    if 'pix' in t:
        return Lancamento.FORMA_PIX
    if any(k in t for k in ('titulo', 'título', 'boleto', 'convenio', 'convênio', 'tributo')):
        return Lancamento.FORMA_BOLETO
    if any(k in t for k in ('debito', 'débito', 'deb ', 'visa electron', 'maestro')):
        return Lancamento.FORMA_DEBITO
    if any(k in t for k in ('credito', 'crédito', 'cartao', 'cartão')):
        return Lancamento.FORMA_CREDITO
    if any(k in t for k in ('salario', 'salário', 'portabilidade', 'ted', 'doc', 'transf', 'tev')):
        return Lancamento.FORMA_TRANSFERENCIA
    if any(k in t for k in ('saque', 'dinheiro', 'especie')):
        return Lancamento.FORMA_DINHEIRO
    return Lancamento.FORMA_PIX


def _sugerir_categoria_receita(user, texto_up: str) -> Categoria:
    qs_receita = Categoria.objects.filter(usuario=user, fator=Categoria.FATOR_RECEITA, pai__isnull=False)
    if any(k in texto_up for k in ('SALARIO', 'SALÁRIO', 'PORTABILIDADE', 'REMUNERACAO', 'FOLHA')):
        return qs_receita.order_by('id').first()
    if any(k in texto_up for k in ('RENDIMENTO', 'DIVIDENDO', 'CDB', 'JUROS', 'POUPANCA')):
        return qs_receita.filter(descricao__icontains='Rendimento').first() or qs_receita.first()
    return qs_receita.filter(descricao__icontains='Restituições').first() or qs_receita.first()


def _sugerir_categoria(user, texto_transacao: str, is_receita: bool) -> Categoria:
    texto_up = texto_transacao.upper()
    if is_receita:
        return _sugerir_categoria_receita(user, texto_up)

    qs_despesa = Categoria.objects.filter(usuario=user, fator=Categoria.FATOR_DESPESA, pai__isnull=False)
    for nome_cat, palavras in MAPA_CATEGORIAS_DESPESA.items():
        if any(p in texto_up for p in palavras):
            cat = qs_despesa.filter(descricao__icontains=nome_cat).first()
            if cat:
                return cat
    return qs_despesa.first()


def _determinar_ciclo_e_origem(perfil, data_tx: datetime.date, texto_transacao: str):
    eh_salario = any(k in texto_transacao.lower() for k in ('salario', 'salário', 'portabilidade'))
    if not perfil.recebe_duas_datas:
        ciclo = Lancamento.CICLO_UNICO
        origem = Lancamento.ORIGEM_SALARIO_UNICO if eh_salario else Lancamento.ORIGEM_NORMAL
        return ciclo, origem

    corte = min(perfil.dia_adiantamento, 19) if (eh_salario and data_tx.day >= 15) else perfil.dia_adiantamento
    ciclo = Lancamento.CICLO_Q1 if data_tx.day >= corte else Lancamento.CICLO_Q2
    if not eh_salario:
        return ciclo, Lancamento.ORIGEM_NORMAL

    origem = Lancamento.ORIGEM_SALARIO_Q1 if ciclo == Lancamento.CICLO_Q1 else Lancamento.ORIGEM_SALARIO_Q2
    return ciclo, origem


def _converter_valor_monetario(valor_str: str) -> Decimal | None:
    if not valor_str:
        return None
    limpo = re.sub(r'[CDcd+-]+$', '', valor_str.replace('R$', '').replace(' ', '').strip())
    limpo = limpo.lstrip('+-').strip()
    if not limpo:
        return None
    if ',' in limpo and '.' in limpo:
        limpo = limpo.replace('.', '').replace(',', '.')
    elif ',' in limpo:
        limpo = limpo.replace(',', '.')
    try:
        dec = Decimal(limpo).quantize(Decimal('0.01'))
        return dec if dec > Decimal('0.00') else None
    except (InvalidOperation, ValueError):
        return None


def _identificar_natureza_receita(descricao: str, sinal_ant: str = '', sinal_pos: str = '', valor_bruto: str = '') -> bool:
    if '-' in (sinal_ant or '') or '-' in (sinal_pos or '') or '-' in (valor_bruto or ''):
        return False
    if (sinal_pos or '').upper() == 'D':
        return False
    if (sinal_pos or '').upper() == 'C' or '+' in (sinal_ant or ''):
        return True

    desc_up = descricao.upper()
    if any(p in desc_up for p in PALAVRAS_DESPESA) and not any(p in desc_up for p in PALAVRAS_RECEITA):
        return False
    return True


def _parse_data_flexivel(data_str: str, ano_padrao: int) -> datetime.date | None:
    s = data_str.strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d/%m/%y', '%d-%m-%Y'):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    if re.match(r'^\d{2}/\d{2}$', s):
        try:
            dia, mes = map(int, s.split('/'))
            return datetime.date(ano_padrao, mes, dia)
        except ValueError:
            return None
    return None


def _salvar_transacao_extraida(user, tx: TransacaoExtraida, evitar_duplicados: bool, obs_origem: str) -> bool:
    if evitar_duplicados and Lancamento.objects.filter(
        usuario=user, data=tx.data, descricao=tx.descricao_limpa, valor=tx.valor
    ).exists():
        return False

    ciclo, origem = _determinar_ciclo_e_origem(user.perfil, tx.data, tx.texto_bruto)
    Lancamento.objects.create(
        usuario=user,
        categoria=_sugerir_categoria(user, tx.texto_bruto, is_receita=tx.eh_receita),
        data=tx.data,
        descricao=tx.descricao_limpa,
        valor=tx.valor,
        forma_pagamento=_detectar_forma_pagamento(tx.texto_bruto),
        ciclo=ciclo,
        status=Lancamento.STATUS_PAGO,
        origem_salarial=origem,
        observacao=obs_origem
    )
    return True


def _persistir_lote_transacoes(user, transacoes: list[TransacaoExtraida], evitar_duplicados: bool, obs_origem: str) -> dict:
    criados = 0
    ignorados = 0
    ultima_data = None
    for tx in transacoes:
        ultima_data = tx.data
        if _salvar_transacao_extraida(user, tx, evitar_duplicados, obs_origem):
            criados += 1
        else:
            ignorados += 1
    return {'criados': criados, 'ignorados': ignorados, 'ultima_data': ultima_data}


def _inferir_ano_documento(texto: str) -> int:
    for padrao in (r'\d{2}/\d{2}/(20\d{2})', r'de\s+[A-Za-zçÇ]+\s+de\s+(20\d{2})'):
        match = re.search(padrao, texto)
        if match:
            return int(match.group(1))
    return datetime.date.today().year


def _extrair_cabecalho_data_pdf(linha: str, ano_contexto: int) -> datetime.date | None:
    match = REGEX_DATA_EXTENSO.search(linha)
    if not match or ('saldo' not in linha.lower() and len(linha) >= 75):
        return None
    dia = int(match.group(1))
    nome_mes = match.group(2).strip()
    ano = int(match.group(3)) if match.group(3) else ano_contexto
    mes = MESES_PT.get(nome_mes) or MESES_PT.get(nome_mes.lower()) or MESES_PT.get(nome_mes.capitalize())
    if not mes:
        return None
    try:
        return datetime.date(ano, mes, dia)
    except ValueError:
        return None


def _parse_linha_pdf_com_aspas(linha: str, data_atual: datetime.date | None) -> TransacaoExtraida | None:
    if not data_atual:
        return None
    match = REGEX_TX_ASPAS.match(linha)
    if not match:
        return None
    tipo_raw, detalhe_raw, valor_raw = match.group(1), match.group(2), match.group(3)
    valor_dec = _converter_valor_monetario(valor_raw)
    if not valor_dec:
        return None
    texto_bruto = f"{tipo_raw} {detalhe_raw}"
    return TransacaoExtraida(
        data=data_atual,
        descricao_limpa=_limpar_descricao(tipo_raw, detalhe_raw),
        texto_bruto=texto_bruto,
        valor=valor_dec,
        eh_receita=_identificar_natureza_receita(texto_bruto, valor_bruto=valor_raw)
    )


def _parse_linha_pdf_tabular(linha: str, ano_contexto: int) -> TransacaoExtraida | None:
    match = REGEX_TX_LINHA_DATA.match(linha)
    if not match:
        return None
    dt = _parse_data_flexivel(match.group('data'), ano_contexto)
    desc_raw = match.group('descricao')
    valor_dec = _converter_valor_monetario(match.group('valor'))
    if not dt or not valor_dec or _eh_linha_ignorada(desc_raw):
        return None
    return TransacaoExtraida(
        data=dt,
        descricao_limpa=_limpar_descricao(desc_raw),
        texto_bruto=desc_raw,
        valor=valor_dec,
        eh_receita=_identificar_natureza_receita(desc_raw, match.group('sinal_ant'), match.group('sinal_pos'))
    )


def _parse_linha_pdf_agrupada(linha: str, data_atual: datetime.date | None) -> TransacaoExtraida | None:
    if not data_atual:
        return None
    match = REGEX_TX_SEM_DATA_NA_LINHA.match(linha)
    if not match:
        return None
    desc_raw = match.group('descricao')
    valor_dec = _converter_valor_monetario(match.group('valor'))
    if not valor_dec or _eh_linha_ignorada(desc_raw):
        return None
    return TransacaoExtraida(
        data=data_atual,
        descricao_limpa=_limpar_descricao(desc_raw),
        texto_bruto=desc_raw,
        valor=valor_dec,
        eh_receita=_identificar_natureza_receita(desc_raw, match.group('sinal_ant'), match.group('sinal_pos'))
    )


@transaction.atomic
def importar_extrato_pdf(user, arquivo_pdf, evitar_duplicados=True, banco_selecionado='AUTO') -> dict:
    """
    Parser Universal de Extratos Bancários em PDF (Inter, Itaú, Bradesco, Santander, BB, Caixa, C6, Nubank).
    """
    reader = PdfReader(arquivo_pdf)
    texto_completo = "\n".join(page.extract_text() or "" for page in reader.pages)
    ano_contexto = _inferir_ano_documento(texto_completo)
    data_atual = None
    transacoes = []

    for linha in texto_completo.splitlines():
        linha_limpa = linha.replace('\xa0', ' ').strip()
        if not linha_limpa:
            continue

        nova_data = _extrair_cabecalho_data_pdf(linha_limpa, ano_contexto)
        if nova_data:
            data_atual = nova_data
            ano_contexto = nova_data.year
            continue

        tx = _parse_linha_pdf_com_aspas(linha_limpa, data_atual)
        if not tx and not _eh_linha_ignorada(linha_limpa):
            tx = _parse_linha_pdf_tabular(linha_limpa, ano_contexto) or _parse_linha_pdf_agrupada(linha_limpa, data_atual)
            if tx:
                data_atual = tx.data

        if tx:
            transacoes.append(tx)

    nome_banco = NOMES_BANCOS.get(banco_selecionado, 'Extrato PDF')
    return _persistir_lote_transacoes(user, transacoes, evitar_duplicados, f"Importado automaticamente via Extrato PDF ({nome_banco})")


def _parse_linha_csv(partes: list[str], ano_padrao: int) -> TransacaoExtraida | None:
    if len(partes) < 2:
        return None

    data_tx, idx_data = None, -1
    for idx, col in enumerate(partes[:3]):
        dt = _parse_data_flexivel(col, ano_padrao)
        if dt:
            data_tx, idx_data = dt, idx
            break
    if not data_tx:
        return None

    valor_dec, eh_receita, textos = None, False, []
    for idx, col in enumerate(partes):
        if idx == idx_data or not col.strip():
            continue
        c_limpa = col.strip()
        val_cand = _converter_valor_monetario(c_limpa)
        eh_numero_puro = bool(re.match(r'^[-+R\$\s]*[\d\.,]+\s*[CDcd+-]?$', c_limpa))
        if val_cand and eh_numero_puro and valor_dec is None:
            valor_dec = val_cand
            eh_receita = not ('-' in c_limpa or c_limpa.upper().endswith('D'))
        else:
            textos.append(c_limpa)

    descricao_limpa = _limpar_descricao(" - ".join(textos))
    if not valor_dec or _eh_linha_ignorada(descricao_limpa):
        return None
    return TransacaoExtraida(data_tx, descricao_limpa, descricao_limpa, valor_dec, eh_receita)


@transaction.atomic
def importar_extrato_csv(user, arquivo_csv, banco_selecionado: str = 'AUTO', evitar_duplicados=True) -> dict:
    """
    Parser Universal para extratos CSV de qualquer banco com separador ',' ou ';'.
    """
    texto = _decodificar_bytes(arquivo_csv.read())
    delimitador = ';' if texto.count(';') > texto.count(',') else ','
    leitor = csv.reader(io.StringIO(texto), delimiter=delimitador)
    ano_padrao = datetime.date.today().year

    transacoes = [tx for partes in leitor if (tx := _parse_linha_csv(partes, ano_padrao)) is not None]
    nome_banco = NOMES_BANCOS.get(banco_selecionado, banco_selecionado)
    return _persistir_lote_transacoes(user, transacoes, evitar_duplicados, f"Importado automaticamente via Extrato CSV ({nome_banco})")


def _parse_bloco_ofx(bloco: str) -> TransacaoExtraida | None:
    dt_match = re.search(r'<DTPOSTED>\s*(\d{8})', bloco, re.IGNORECASE)
    amt_match = re.search(r'<TRNAMT>\s*([-+]?[\d\.,]+)', bloco, re.IGNORECASE)
    if not dt_match or not amt_match:
        return None

    try:
        data_tx = datetime.datetime.strptime(dt_match.group(1), '%Y%m%d').date()
        valor_signed = Decimal(amt_match.group(1).strip().replace(',', '.')).quantize(Decimal('0.01'))
    except (ValueError, InvalidOperation):
        return None
    if valor_signed == Decimal('0.00'):
        return None

    memo_m = re.search(r'<MEMO>\s*([^\r\n<]+)', bloco, re.IGNORECASE)
    name_m = re.search(r'<NAME>\s*([^\r\n<]+)', bloco, re.IGNORECASE)
    memo = memo_m.group(1).strip() if memo_m else ''
    name = name_m.group(1).strip() if name_m else ''
    desc = _limpar_descricao(name or memo, memo if (name and memo and memo != name) else '')
    return TransacaoExtraida(data_tx, desc, desc, abs(valor_signed), valor_signed > Decimal('0.00'))


@transaction.atomic
def importar_extrato_ofx(user, arquivo_ofx, banco_selecionado: str = 'AUTO', evitar_duplicados=True) -> dict:
    """
    Parser Universal para arquivos OFX (Open Financial Exchange) de qualquer banco.
    """
    texto = _decodificar_bytes(arquivo_ofx.read())
    blocos = re.findall(r'<STMTTRN>(.*?)</STMTTRN>', texto, flags=re.DOTALL | re.IGNORECASE)
    if not blocos:
        partes_sgml = re.split(r'<STMTTRN>', texto, flags=re.IGNORECASE)
        blocos = partes_sgml[1:] if len(partes_sgml) > 1 else []

    transacoes = [tx for b in blocos if (tx := _parse_bloco_ofx(b)) is not None]
    nome_banco = NOMES_BANCOS.get(banco_selecionado, banco_selecionado)
    return _persistir_lote_transacoes(user, transacoes, evitar_duplicados, f"Importado automaticamente via Extrato OFX ({nome_banco})")


def processar_importacao_extrato(user, banco: str, arquivo, evitar_duplicados: bool = True) -> dict:
    """
    Fachada Universal (Facade Pattern) que direciona o extrato para o parser (.PDF, .CSV ou .OFX).
    """
    ext = os.path.splitext(arquivo.name)[1].lower()
    if ext == '.pdf':
        return importar_extrato_pdf(user, arquivo, evitar_duplicados=evitar_duplicados, banco_selecionado=banco)
    if ext == '.ofx':
        return importar_extrato_ofx(user, arquivo, banco_selecionado=banco, evitar_duplicados=evitar_duplicados)
    return importar_extrato_csv(user, arquivo, banco_selecionado=banco, evitar_duplicados=evitar_duplicados)
