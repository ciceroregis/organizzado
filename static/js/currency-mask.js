/**
 * Módulo de Máscara Monetária Brasileira (R$ 1.234,56)
 */
function formatarMoedaBR(valorBruto) {
    if (!valorBruto) return '';
    const apenasDigitos = String(valorBruto).replace(/\D/g, '');
    if (!apenasDigitos) return '';
    const numero = parseInt(apenasDigitos, 10);
    if (isNaN(numero)) return '';
    const centavos = (numero / 100).toFixed(2);
    const partes = centavos.split('.');
    partes[0] = partes[0].replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    return 'R$ ' + partes[0] + ',' + partes[1];
}

function aplicarMascaraMonetaria(input) {
    if (input.value && !input.value.includes(',')) {
        const num = parseFloat(input.value);
        if (!isNaN(num)) {
            input.value = formatarMoedaBR(Math.round(num * 100));
        }
    }
    input.addEventListener('input', function () {
        const pos = this.value;
        if (!pos.replace(/\D/g, '')) {
            this.value = '';
            return;
        }
        this.value = formatarMoedaBR(pos);
    });
}

document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.mask-money').forEach(aplicarMascaraMonetaria);
});
