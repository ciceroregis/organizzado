/**
 * Módulo de Interações da Matriz de Fluxo de Caixa Quinzenal / Mensal
 * - Alocação automática de ciclo salarial ao alterar a data
 * - Preenchimento do modal de edição manual de lançamentos/salários
 * - Preenchimento do modal Bootstrap de confirmação de exclusão
 */
document.addEventListener('DOMContentLoaded', function () {
    const container = document.getElementById('fluxo-quinzenal-config');
    const diaCorte = container ? parseInt(container.dataset.diaCorte || '15', 10) : 15;
    const recebeDuasDatas = container ? (container.dataset.recebeDuasDatas === 'true') : true;

    // 1. Auto-seleciona o ciclo (1º Ciclo vs 2º Ciclo) ao mudar a data no modal de Novo Lançamento
    const inputData = document.querySelector('#modalNovoLancamento input[name="data"]');
    const selectCiclo = document.querySelector('#modalNovoLancamento select[name="ciclo"]');

    if (inputData && selectCiclo && recebeDuasDatas) {
        inputData.addEventListener('change', function () {
            const partes = this.value.split('-');
            if (partes.length === 3) {
                const dia = parseInt(partes[2], 10);
                selectCiclo.value = (dia >= diaCorte) ? 'Q1_ADIANTAMENTO' : 'Q2_FECHAMENTO';
            }
        });
    }

    // 2. Popula o modal de edição manual de lançamento / salário (delegação de eventos)
    document.addEventListener('click', function (e) {
        const btnEditar = e.target.closest('.btn-editar-lancamento');
        if (btnEditar) {
            const elId = document.getElementById('edit_lancamento_id');
            if (!elId) return;
            elId.value = btnEditar.getAttribute('data-id') || '';
            document.getElementById('edit_data').value = btnEditar.getAttribute('data-data') || '';
            document.getElementById('edit_descricao').value = btnEditar.getAttribute('data-descricao') || '';
            document.getElementById('edit_categoria').value = btnEditar.getAttribute('data-categoria') || '';
            document.getElementById('edit_valor').value = btnEditar.getAttribute('data-valor') || '';
            document.getElementById('edit_forma_pagamento').value = btnEditar.getAttribute('data-forma') || 'PIX';
            document.getElementById('edit_ciclo').value = btnEditar.getAttribute('data-ciclo') || 'Q2_FECHAMENTO';
            document.getElementById('edit_status').value = btnEditar.getAttribute('data-status') || 'PAGO';
            document.getElementById('edit_observacao').value = btnEditar.getAttribute('data-observacao') || '';
            document.getElementById('edit_fixo').checked = (btnEditar.getAttribute('data-fixo') === 'true');
            return;
        }

        // 3. Popula o Modal Bootstrap de Confirmação de Exclusão
        const btnExcluir = e.target.closest('.btn-excluir-modal');
        if (btnExcluir) {
            const formModal = document.getElementById('formConfirmarExclusaoModal');
            if (!formModal) return;

            const actionUrl = btnExcluir.getAttribute('data-action-url') || '';
            const descricao = btnExcluir.getAttribute('data-descricao') || 'Item selecionado';
            const valor = btnExcluir.getAttribute('data-valor') || '';
            const dataTx = btnExcluir.getAttribute('data-data') || '';
            const acaoHidden = btnExcluir.getAttribute('data-acao') || '';
            const catId = btnExcluir.getAttribute('data-categoria-id') || '';

            formModal.setAttribute('action', actionUrl);
            document.getElementById('exclusao_item_descricao').textContent = descricao;

            const detalhesParts = [];
            if (dataTx) detalhesParts.push('Data: ' + dataTx);
            if (valor) detalhesParts.push('Valor: ' + valor);
            document.getElementById('exclusao_item_detalhes').textContent = detalhesParts.join(' • ');

            const inputAcao = document.getElementById('exclusao_hidden_acao');
            const inputCat = document.getElementById('exclusao_hidden_categoria_id');
            if (inputAcao) inputAcao.value = acaoHidden;
            if (inputCat) inputCat.value = catId;
        }
    });
});
