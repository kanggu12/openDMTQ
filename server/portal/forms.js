// The site's own check of what a form needs before it goes, in place of the browser's: its bubbles speak the browser's
// language rather than the page's, and look like nothing on the site. Every form marked novalidate is checked here: a field
// it needs left empty (data-missing), or one its own rules refuse (data-invalid: a pattern, a number's bounds, a type),
// stops the form; that field's words show in the site's error box above the form (the box the server's own answer uses,
// .error in style.css), and the field takes the focus, marked for screen readers too. The server checks the same again,
// so a browser without scripts loses nothing but this early word. A form that goes says so on its button while the next
// page comes (aria-busy, style.css).
//
// For another page's forms (the admin pages', say): novalidate on the form; on each field it checks, data-missing="<the
// words, in the page's language>" when it must be filled and data-invalid="<the words>" when its pattern, min, max or type
// must hold; and this file, loaded with defer.
(() => {
  // What is wrong with a field, in its own words, or '' when nothing is: empty first, then its own rules.
  const fault = f => {
    if (f.disabled) return '';
    if (f.dataset.missing !== undefined && f.value.trim() === '') return f.dataset.missing;
    if (f.dataset.invalid !== undefined && f.value.trim() !== '' && !f.validity.valid) return f.dataset.invalid;
    return '';
  };
  for (const form of document.querySelectorAll('form[novalidate]')) {
    form.addEventListener('submit', e => {
      // The first field, in the order of the form, that cannot go as it is.
      const wrong = [...form.querySelectorAll('[data-missing], [data-invalid]')].find(f => fault(f) !== '');
      if (!wrong) {
        // On its way: the button that sent it shows that it is working (a wrong password takes a second to answer).
        const button = e.submitter || form.querySelector('button:not([type=button])');
        if (button) button.setAttribute('aria-busy', 'true');
        return;
      }
      e.preventDefault();
      // The box right above the form: the one the server's answer put there, or a new one in the same place.
      let box = form.previousElementSibling;
      if (!box || !box.matches('.error')) {
        box = document.createElement('p');
        box.className = 'error';
        box.setAttribute('role', 'alert');
        form.before(box);
      }
      box.textContent = fault(wrong);
      // The field marked, and named by the box, for whoever cannot see where the words are.
      if (!box.id) box.id = `${form.className.split(' ')[0] || 'form'}-says`;
      for (const f of form.querySelectorAll('[aria-invalid]')) f.removeAttribute('aria-invalid');
      wrong.setAttribute('aria-invalid', 'true');
      wrong.setAttribute('aria-describedby', box.id);
      wrong.focus();
    });
    // Typing into a marked field takes its mark away: what it says is up to the next press of the button.
    form.addEventListener('input', e => {
      if (e.target.getAttribute('aria-invalid') === 'true') e.target.removeAttribute('aria-invalid');
    });
  }
})();
