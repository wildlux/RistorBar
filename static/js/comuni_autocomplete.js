/**
 * Autocomplete comuni italiani da static/data/comuni.json
 * Formato dati: [ [nome, sigla_provincia, regione], ... ]
 *
 * Uso: aggiungi data-comuni="citta" a un <input> per autocomplete città,
 *      data-comuni="provincia" a un <input> per autocomplete provincia.
 *      Opzionale: data-comuni-link="#altro-input" per aggiornare la provincia
 *      automaticamente quando si seleziona una città.
 */
(function () {
  let _comuni = null;

  function loadComuni(cb) {
    if (_comuni) return cb(_comuni);
    fetch('/static/data/comuni.json')
      .then(r => r.json())
      .then(data => { _comuni = data; cb(data); });
  }

  function makeDatalist(id, items) {
    let dl = document.getElementById(id);
    if (!dl) {
      dl = document.createElement('datalist');
      dl.id = id;
      document.body.appendChild(dl);
    }
    dl.innerHTML = '';
    items.slice(0, 300).forEach(([nome, sigla, regione]) => {
      const opt = document.createElement('option');
      opt.value = nome;
      opt.label = sigla + ' — ' + regione;
      dl.appendChild(opt);
    });
  }

  function initCittaInput(input) {
    const dlId = 'dl-comuni-' + Math.random().toString(36).slice(2);
    input.setAttribute('list', dlId);
    input.setAttribute('autocomplete', 'off');

    const provinciaTarget = input.dataset.comuniLink
      ? document.querySelector(input.dataset.comuniLink)
      : null;

    input.addEventListener('input', function () {
      const q = this.value.trim().toLowerCase();
      if (q.length < 2) return;
      loadComuni(comuni => {
        const matches = comuni.filter(([nome]) => nome.toLowerCase().startsWith(q));
        makeDatalist(dlId, matches);
      });
    });

    // Quando l'utente sceglie un comune, compila automaticamente la provincia
    if (provinciaTarget) {
      input.addEventListener('change', function () {
        const val = this.value.trim().toLowerCase();
        loadComuni(comuni => {
          const found = comuni.find(([nome]) => nome.toLowerCase() === val);
          if (found) provinciaTarget.value = found[1]; // sigla provincia
        });
      });
    }
  }

  function initProvinciaInput(input) {
    const dlId = 'dl-province';
    input.setAttribute('list', dlId);
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('maxlength', '2');
    input.style.textTransform = 'uppercase';

    loadComuni(comuni => {
      // Ricava sigle uniche
      const sigle = [...new Set(comuni.map(c => c[1]))].sort();
      let dl = document.getElementById(dlId);
      if (!dl) {
        dl = document.createElement('datalist');
        dl.id = dlId;
        document.body.appendChild(dl);
        sigle.forEach(sigla => {
          const opt = document.createElement('option');
          opt.value = sigla;
          dl.appendChild(opt);
        });
      }
    });

    input.addEventListener('input', function () {
      this.value = this.value.toUpperCase();
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-comuni="citta"]').forEach(initCittaInput);
    document.querySelectorAll('[data-comuni="provincia"]').forEach(initProvinciaInput);
  });
})();
