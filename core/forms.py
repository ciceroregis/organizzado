import os
from decimal import Decimal, InvalidOperation
from django import forms
from django.contrib.auth.models import User
from .models import PerfilFinanceiro, Categoria, Lancamento

MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
EXTENSOES_PERMITIDAS = {'.pdf', '.csv', '.ofx'}


class MoedaBRField(forms.CharField):
    """
    Campo de formulário que aceita valores formatados com máscara monetária brasileira
    (ex: 'R$ 8.500,00', '8.500,00', '-1.250,50' ou '8500.00') e converte para Decimal.
    """
    def __init__(self, *args, permite_negativo=False, **kwargs):
        self.permite_negativo = permite_negativo
        kwargs.setdefault('widget', forms.TextInput(attrs={
            'class': 'form-control mask-money',
            'inputmode': 'numeric',
            'placeholder': 'R$ 0,00',
            'autocomplete': 'off',
        }))
        super().__init__(*args, **kwargs)

    def prepare_value(self, value):
        if value is None or value == '':
            return ''
        if isinstance(value, str) and ',' in value:
            return value
        try:
            dec = Decimal(str(value)).quantize(Decimal('0.01'))
            neg = '-' if dec < 0 else ''
            inteiro, centavos = f"{abs(dec):.2f}".split('.')
            inteiro_fmt = f"{int(inteiro):,}".replace(',', '.')
            return f"R$ {neg}{inteiro_fmt},{centavos}"
        except (InvalidOperation, ValueError, TypeError):
            return value

    def to_python(self, value):
        if value is None:
            return None
        val_str = str(value).strip()
        if not val_str:
            return None
        negativo = '-' in val_str and self.permite_negativo
        limpo = val_str.replace('R$', '').replace(' ', '').replace('-', '').strip()
        if not limpo:
            return None
        if ',' in limpo:
            limpo = limpo.replace('.', '').replace(',', '.')
        try:
            dec = Decimal(limpo).quantize(Decimal('0.01'))
            return -dec if negativo else dec
        except (InvalidOperation, ValueError):
            raise forms.ValidationError('Informe um valor monetário válido (ex: R$ 1.500,00).')


class RegistroUsuarioForm(forms.ModelForm):
    nome_completo = forms.CharField(
        max_length=120, label='Nome Completo',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Carlos Eduardo Silva'})
    )
    cpf = forms.CharField(
        max_length=14, label='CPF', required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '000.000.000-00'})
    )
    celular = forms.CharField(
        max_length=20, label='Celular', required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '(11) 99999-9999'})
    )
    recebe_duas_datas = forms.BooleanField(
        required=False, initial=True,
        label='Recebo meu salário dividido em 2 datas no mês (ex: Dia 05 e Dia 20)',
        widget=forms.CheckboxInput(attrs={'id': 'id_recebe_duas_datas', 'class': 'form-check-input'})
    )
    salario_bruto_mensal = MoedaBRField(
        required=False,
        initial=Decimal('0.00'),
        label='Salário Mensal Total (R$)'
    )
    percentual_adiantamento = forms.DecimalField(
        required=False,
        max_digits=5, decimal_places=2, initial=Decimal('40.00'),
        label='% do 2º Recebimento (Meio do Mês)',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '1'})
    )
    senha = forms.CharField(
        label='Senha',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    confirmar_senha = forms.CharField(
        label='Confirmar Senha',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = User
        fields = ['username', 'email']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Login de acesso'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'seu@email.com'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('senha') != cleaned_data.get('confirmar_senha'):
            self.add_error('confirmar_senha', 'A confirmação de senha não confere.')
        return cleaned_data


class PerfilSalarialForm(forms.ModelForm):
    saldo_inicial = MoedaBRField(required=False, permite_negativo=True, label='Saldo Inicial em Caixa (R$)')
    salario_bruto_mensal = MoedaBRField(required=True, label='Salário Mensal Base Total (R$)')
    valor_fechamento_manual = MoedaBRField(
        required=False,
        label='Valor Manual do 1º Recebimento (R$)',
        widget=forms.TextInput(attrs={
            'class': 'form-control mask-money',
            'inputmode': 'numeric',
            'placeholder': 'Opcional: R$ 0,00 (Automático se vazio)',
            'autocomplete': 'off',
        })
    )
    valor_adiantamento_manual = MoedaBRField(
        required=False,
        label='Valor Manual do 2º Recebimento (R$)',
        widget=forms.TextInput(attrs={
            'class': 'form-control mask-money',
            'inputmode': 'numeric',
            'placeholder': 'Opcional: R$ 0,00 (Automático se vazio)',
            'autocomplete': 'off',
        })
    )

    class Meta:
        model = PerfilFinanceiro
        fields = [
            'recebe_duas_datas',
            'saldo_inicial',
            'salario_bruto_mensal',
            'percentual_adiantamento',
            'valor_fechamento_manual',
            'valor_adiantamento_manual',
            'dia_adiantamento',
            'usa_quinto_dia_util',
            'dia_fechamento_fixo',
        ]
        widgets = {
            'recebe_duas_datas': forms.CheckboxInput(attrs={'id': 'id_recebe_duas_datas', 'class': 'form-check-input', 'role': 'switch'}),
            'percentual_adiantamento': forms.NumberInput(attrs={'id': 'id_percentual_adiantamento', 'class': 'form-control', 'step': '1', 'min': '0', 'max': '100'}),
            'dia_adiantamento': forms.NumberInput(attrs={'id': 'id_dia_adiantamento', 'class': 'form-control', 'min': '1', 'max': '31'}),
            'usa_quinto_dia_util': forms.CheckboxInput(attrs={'id': 'id_usa_quinto_dia_util', 'class': 'form-check-input'}),
            'dia_fechamento_fixo': forms.NumberInput(attrs={'id': 'id_dia_fechamento_fixo', 'class': 'form-control', 'min': '1', 'max': '31'}),
        }

    def clean_saldo_inicial(self):
        val = self.cleaned_data.get('saldo_inicial')
        return val if val is not None else Decimal('0.00')


class CategoriaForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['pai'].queryset = Categoria.objects.filter(usuario=user, pai__isnull=True)
            self.fields['pai'].required = True

    class Meta:
        model = Categoria
        fields = ['pai', 'descricao', 'ciclo_sugerido', 'icone']
        widgets = {
            'pai': forms.Select(attrs={'class': 'form-select'}),
            'descricao': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome da subcategoria'}),
            'ciclo_sugerido': forms.Select(attrs={'class': 'form-select'}),
            'icone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'bi-tag'}),
        }


class LancamentoForm(forms.ModelForm):
    valor = MoedaBRField(
        required=True,
        label='Valor (R$)',
        widget=forms.TextInput(attrs={
            'class': 'form-control mask-money fw-bold',
            'inputmode': 'numeric',
            'placeholder': 'R$ 0,00',
            'autocomplete': 'off',
        })
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['categoria'].queryset = Categoria.objects.filter(
                usuario=user, pai__isnull=False
            ).select_related('pai').order_by('fator', 'descricao')

    class Meta:
        model = Lancamento
        fields = [
            'data', 'descricao', 'categoria', 'valor',
            'forma_pagamento', 'ciclo', 'status',
            'fixo_recorrente', 'observacao'
        ]
        widgets = {
            'data': forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control', 'type': 'date'}),
            'descricao': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Aluguel, Supermercado, Luz...'}),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'forma_pagamento': forms.Select(attrs={'class': 'form-select'}),
            'ciclo': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'fixo_recorrente': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'observacao': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opcional'}),
        }


class ImportarExtratoForm(forms.Form):
    BANCO_AUTO = 'AUTO'
    BANCO_INTER = 'INTER'
    BANCO_NUBANK = 'NUBANK'
    BANCO_ITAU = 'ITAU'
    BANCO_BRADESCO = 'BRADESCO'
    BANCO_SANTANDER = 'SANTANDER'
    BANCO_BB = 'BB'
    BANCO_CAIXA = 'CAIXA'
    BANCO_C6 = 'C6'
    BANCO_SICOOB = 'SICOOB'
    BANCO_OUTRO = 'OUTRO'

    BANCO_CHOICES = [
        (BANCO_AUTO, 'Detecção Automática (Qualquer Banco)'),
        (BANCO_INTER, 'Banco Inter'),
        (BANCO_NUBANK, 'Nubank'),
        (BANCO_ITAU, 'Itaú Unibanco'),
        (BANCO_BRADESCO, 'Bradesco'),
        (BANCO_SANTANDER, 'Santander'),
        (BANCO_BB, 'Banco do Brasil'),
        (BANCO_CAIXA, 'Caixa Econômica Federal'),
        (BANCO_C6, 'C6 Bank'),
        (BANCO_SICOOB, 'Sicoob / Sicredi'),
        (BANCO_OUTRO, 'Outro Banco / Instituição'),
    ]

    banco = forms.ChoiceField(
        choices=BANCO_CHOICES,
        initial=BANCO_AUTO,
        label='Instituição Bancária do Extrato',
        widget=forms.Select(attrs={'id': 'id_banco', 'class': 'form-select'})
    )
    arquivo = forms.FileField(
        label='Arquivo do Extrato (.pdf, .csv ou .ofx)',
        widget=forms.ClearableFileInput(attrs={'id': 'id_arquivo', 'class': 'form-control', 'accept': '.pdf,.csv,.ofx'})
    )
    evitar_duplicados = forms.BooleanField(
        required=False,
        initial=True,
        label='Ignorar transações já importadas anteriormente (mesma data, descrição e valor)',
        widget=forms.CheckboxInput(attrs={'id': 'id_evitar_duplicados', 'class': 'form-check-input'})
    )

    def clean_arquivo(self):
        arquivo = self.cleaned_data.get('arquivo')
        if not arquivo:
            raise forms.ValidationError('Selecione um arquivo de extrato válido.')

        # 1. Validação de tamanho máximo (Proteção contra DoS)
        if arquivo.size > MAX_UPLOAD_SIZE_BYTES:
            raise forms.ValidationError('O arquivo excede o tamanho máximo permitido de 5 MB.')

        # 2. Validação de extensão permitida
        ext = os.path.splitext(arquivo.name)[1].lower()
        if ext not in EXTENSOES_PERMITIDAS:
            raise forms.ValidationError('Formato de arquivo não suportado. Envie arquivos .PDF, .CSV ou .OFX.')

        # 3. Validação de assinatura binária (Magic Bytes) para PDFs
        if ext == '.pdf':
            cabecalho = arquivo.read(5)
            arquivo.seek(0)
            if cabecalho != b'%PDF-':
                raise forms.ValidationError('O arquivo enviado não é um documento PDF válido.')

        return arquivo
