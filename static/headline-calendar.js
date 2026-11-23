// Calendar imports are independent of headline editing and Mailchimp draft state.
document.addEventListener('click', async (event) => {
  const button = event.target.closest('.headline-calendar-button');
  if (!button || button.disabled) return;
  const status = button.closest('.headline-calendar-action').querySelector('.headline-calendar-status');
  button.disabled = true;
  button.textContent = 'Adding…';
  status.textContent = '';
  try {
    const response = await fetch(button.dataset.importUrl, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: button.dataset.articleId}),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'Check the calendar before retrying.');
    }
    button.textContent = data.deduped ? 'Already in Calendar' : 'Added to Calendar';
    status.textContent = data.deduped ? 'This hearing is already in AddEvent.' : 'Hearing added to AddEvent.';
  } catch (error) {
    button.disabled = false;
    button.textContent = 'Add to Calendar';
    status.textContent = `Could not add event. ${error instanceof SyntaxError || error instanceof TypeError ? 'Check the calendar before retrying.' : error.message}`;
  }
});
