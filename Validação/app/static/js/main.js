document.addEventListener('DOMContentLoaded', () => {
  // Marca primeiro item do menu como ativo
  document.querySelector('.sidebar nav ul li a').classList.add('active');

  // Filtro de busca na tabela
  window.filterTable = () => {
    const term = document.getElementById('searchInput').value.toUpperCase();
    document.querySelectorAll('.data-table tbody tr').forEach(row => {
      row.style.display = row.cells[4].textContent.toUpperCase().includes(term) ? '' : 'none';
    });
  };
});
