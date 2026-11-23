/* Shared headline review dragging; nesting is enabled for Main Newsletter. */
function setupHeadlineDrag({moveUrl, nestingEnabled}) {
  const sortables = [];
  const status = document.getElementById('headline-save-status');
  let dragged = null;
  let origin = null;
  let attachTarget = null;
  let dropIntent = null;
  let insertionMarker = null;
  let saving = false;
  let disabledControls = [];

  const groups = (list) => Array.from(list.children).filter((el) => el.matches('.headline-group'));
  const childList = (group) => group.querySelector(':scope > .headline-children');
  const hasChildren = (group) => childList(group)?.querySelector('.headline-group');

  function setSaving(value) {
    saving = value;
    sortables.forEach((sortable) => sortable.option('disabled', value));
    if (value) {
      disabledControls = Array.from(document.querySelectorAll(
        '.workflow-actions button:not(:disabled), .edit-title-btn:not(:disabled), .save-title-btn:not(:disabled)'
      ));
      disabledControls.forEach((button) => { button.disabled = true; });
    } else {
      disabledControls.forEach((button) => { button.disabled = false; });
      disabledControls = [];
    }
  }

  function highlight(target) {
    if (attachTarget === target) return;
    attachTarget?.querySelector(':scope > .headline-card')?.classList.remove('headline-attach-target');
    attachTarget = target;
    attachTarget?.querySelector(':scope > .headline-card')?.classList.add('headline-attach-target');
  }

  function trackTarget(event) {
    if (!dragged || !nestingEnabled) return;
    insertionMarker?.classList.remove('headline-insert-before', 'headline-insert-after');
    insertionMarker = null;
    dropIntent = null;
    highlight(null);
    const pointer = event.touches?.[0] || event;
    const element = document.elementFromPoint(pointer.clientX, pointer.clientY);
    if (!element || dragged.contains(element)) return;
    const card = element.closest('.headline-card');
    let target = card?.parentElement;
    if (target && !target.parentElement.dataset.parentId && !hasChildren(dragged)) {
      const rect = card.getBoundingClientRect();
      const edge = Math.min(18, rect.height * 0.15);
      if (pointer.clientY > rect.top + edge && pointer.clientY < rect.bottom - edge) {
        highlight(target);
        dropIntent = {list: childList(target), before: null};
      }
    }
    if (!dropIntent) {
      // A whole group can only move among main articles. Hovering one of
      // another group's children therefore targets that whole group.
      if (target?.parentElement.dataset.parentId && hasChildren(dragged)) {
        target = target.parentElement.parentElement;
      }
      const list = target?.parentElement || element.closest('.headline-sortable')
        || element.closest('.headline-category')?.querySelector('.headline-article-list');
      if (!list || dragged.contains(list)) return;
      const candidates = groups(list).filter((group) => group !== dragged);
      let before;
      if (target) {
        const rect = target === card.parentElement
          ? card.getBoundingClientRect() : target.getBoundingClientRect();
        before = pointer.clientY < rect.top + rect.height / 2
          ? target : candidates[candidates.indexOf(target) + 1] || null;
      } else {
        before = candidates.find((group) => {
          const rect = group.getBoundingClientRect();
          return pointer.clientY < rect.top + rect.height / 2;
        }) || null;
      }
      if (list.dataset.parentId && hasChildren(dragged)) return;
      dropIntent = {list, before};
      insertionMarker = before || candidates[candidates.length - 1];
      insertionMarker?.classList.add(before ? 'headline-insert-before' : 'headline-insert-after');
    }
    if (event.type === 'dragover' && dropIntent) {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    }
  }

  document.addEventListener('dragover', trackTarget, true);
  document.addEventListener('touchmove', trackTarget, {capture: true, passive: true});
  document.addEventListener('pointermove', trackTarget, true);

  async function finishMove(event) {
    const item = event.item;
    if (dropIntent) dropIntent.list.insertBefore(item, dropIntent.before);
    dropIntent = null;
    insertionMarker?.classList.remove('headline-insert-before', 'headline-insert-after');
    insertionMarker = null;
    highlight(null);
    dragged = null;
    const destination = item.parentElement;
    const newIndex = groups(destination).indexOf(item);
    const previous = origin;
    origin = null;
    if (destination === previous.list && newIndex === previous.index) return;

    setSaving(true);
    status.textContent = 'Saving article arrangement…';
    try {
      const response = await fetch(moveUrl, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          id: item.dataset.id,
          from_category: previous.category,
          to_category: destination.closest('.headline-category').dataset.category,
          parent_id: destination.dataset.parentId || null,
          new_index: newIndex,
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || 'Move failed');
      status.textContent = 'Article arrangement saved.';
      document.querySelector('[data-update-draft]')?.removeAttribute('hidden');
    } catch (error) {
      // Restore the whole group, including any attached articles.
      previous.list.insertBefore(item, groups(previous.list).filter((el) => el !== item)[previous.index] || null);
      status.textContent = `Couldn't save that move: ${error.message}. Please try again.`;
    } finally {
      setSaving(false);
    }
  }

  document.querySelectorAll('.headline-sortable').forEach((list) => {
    sortables.push(new Sortable(list, {
      group: {
        name: 'headline-categories',
        put: !nestingEnabled,
      },
      // Keep targets stationary while choosing between attach and reorder.
      // Commit the indicated placement only on release, so crossing an edge
      // on the way to a card's center cannot swap that card out from under us.
      sort: !nestingEnabled,
      draggable: '.headline-group',
      animation: 150,
      handle: '.headline-drag-handle',
      ghostClass: 'dragging',
      filter: 'a, button, input',
      preventOnFilter: false,
      fallbackTolerance: 4,
      onStart: (event) => {
        dragged = event.item;
        origin = {
          list: event.from,
          index: groups(event.from).indexOf(event.item),
          category: event.from.closest('.headline-category').dataset.category,
        };
      },
      onMove: (event, originalEvent) => {
        trackTarget(originalEvent);
        if (nestingEnabled) return false;
      },
      onEnd: finishMove,
    }));
  });

  document.querySelectorAll('.workflow-actions form').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (saving) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    });
  });
  return {setSaving, isSaving: () => saving};
}
