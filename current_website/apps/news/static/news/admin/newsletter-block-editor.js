(function () {
  function parseJsonScript(scriptId) {
    var node = scriptId ? document.getElementById(scriptId) : null;
    if (!node) {
      return [];
    }
    try {
      return JSON.parse(node.textContent || '[]');
    } catch (error) {
      return [];
    }
  }

  function deepClone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  var BLOCK_LABELS = {
    heading: 'Heading',
    paragraph: 'Paragraph',
    list: 'Bullet list',
    image: 'Image',
    button: 'Button',
    quote: 'Quote',
    divider: 'Divider',
    spacer: 'Spacer'
  };

  var BLOCK_TEMPLATES = {
    heading: function () {
      return { type: 'heading', text: 'Section heading', level: '2', align: 'left' };
    },
    paragraph: function () {
      return { type: 'paragraph', text: 'Add the main body copy here.', style: 'body', align: 'left' };
    },
    list: function () {
      return { type: 'list', items: ['First point', 'Second point'] };
    },
    image: function () {
      return { type: 'image', image_asset_id: '', image_url: '', alt_text: '', caption: '', link_url: '', width: 'full' };
    },
    button: function () {
      return { type: 'button', text: 'Learn more', url: '', style: 'primary', align: 'left' };
    },
    quote: function () {
      return { type: 'quote', text: 'Add a testimonial or highlighted statement.', attribution: '' };
    },
    divider: function () {
      return { type: 'divider' };
    },
    spacer: function () {
      return { type: 'spacer', size: 'md' };
    }
  };

  var BLOCK_FIELDS = {
    heading: [
      { key: 'text', label: 'Text', type: 'textarea', rows: 3 },
      { key: 'level', label: 'Size', type: 'select', options: [['1', 'Large'], ['2', 'Medium'], ['3', 'Small']] },
      { key: 'align', label: 'Alignment', type: 'select', options: [['left', 'Left'], ['center', 'Center']] }
    ],
    paragraph: [
      { key: 'text', label: 'Text', type: 'textarea', rows: 6 },
      { key: 'style', label: 'Style', type: 'select', options: [['body', 'Body'], ['lead', 'Lead'], ['small', 'Small']] },
      { key: 'align', label: 'Alignment', type: 'select', options: [['left', 'Left'], ['center', 'Center']] }
    ],
    list: [
      { key: 'items', label: 'Items', type: 'textarea', rows: 6, help: 'One bullet per line.' }
    ],
    image: [
      { key: 'image_asset_id', label: 'Uploaded image', type: 'asset-select', help: 'Choose an uploaded newsletter image or leave blank to use an external URL.' },
      { key: 'image_url', label: 'Image URL', type: 'url' },
      { key: 'alt_text', label: 'Alt text', type: 'text' },
      { key: 'caption', label: 'Caption', type: 'textarea', rows: 3 },
      { key: 'link_url', label: 'Link URL', type: 'url' },
      { key: 'width', label: 'Width', type: 'select', options: [['full', 'Full'], ['wide', 'Wide'], ['narrow', 'Narrow']] }
    ],
    button: [
      { key: 'text', label: 'Label', type: 'text' },
      { key: 'url', label: 'URL', type: 'url' },
      { key: 'style', label: 'Style', type: 'select', options: [['primary', 'Primary'], ['secondary', 'Secondary']] },
      { key: 'align', label: 'Alignment', type: 'select', options: [['left', 'Left'], ['center', 'Center']] }
    ],
    quote: [
      { key: 'text', label: 'Quote', type: 'textarea', rows: 4 },
      { key: 'attribution', label: 'Attribution', type: 'text' }
    ],
    spacer: [
      { key: 'size', label: 'Height', type: 'select', options: [['sm', 'Small'], ['md', 'Medium'], ['lg', 'Large']] }
    ],
    divider: []
  };

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function toMultiline(value) {
    if (Array.isArray(value)) {
      return value.join('\n');
    }
    return value || '';
  }

  function fromMultiline(value) {
    return String(value || '')
      .split(/\r?\n/)
      .map(function (line) { return line.trim(); })
      .filter(Boolean);
  }

  function createButton(label, onClick) {
    var button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.addEventListener('click', onClick);
    return button;
  }

  function resolvePreviewImage(block, imageAssetsById) {
    var asset = block.image_asset_id ? imageAssetsById[String(block.image_asset_id)] : null;
    return {
      image_url: block.image_url || (asset && asset.url) || '',
      alt_text: block.alt_text || (asset && asset.alt_text) || '',
      caption: block.caption || (asset && asset.caption) || ''
    };
  }

  function renderField(block, field, onChange, libraries) {
    var wrapper = document.createElement('div');
    wrapper.className = 'newsletter-block-editor__field';

    var label = document.createElement('label');
    label.textContent = field.label;
    wrapper.appendChild(label);

    var input;
    if (field.type === 'asset-select') {
      input = document.createElement('select');
      var blankOption = document.createElement('option');
      blankOption.value = '';
      blankOption.textContent = 'Choose uploaded image';
      input.appendChild(blankOption);
      libraries.imageAssets.forEach(function (asset) {
        var optionNode = document.createElement('option');
        optionNode.value = String(asset.id);
        optionNode.textContent = asset.name;
        if (String(block[field.key] || '') === String(asset.id)) {
          optionNode.selected = true;
        }
        input.appendChild(optionNode);
      });
    } else if (field.type === 'select') {
      input = document.createElement('select');
      field.options.forEach(function (option) {
        var optionNode = document.createElement('option');
        optionNode.value = option[0];
        optionNode.textContent = option[1];
        if ((block[field.key] || '') === option[0]) {
          optionNode.selected = true;
        }
        input.appendChild(optionNode);
      });
    } else if (field.type === 'textarea') {
      input = document.createElement('textarea');
      input.rows = field.rows || 4;
      input.value = toMultiline(block[field.key]);
    } else {
      input = document.createElement('input');
      input.type = field.type || 'text';
      input.value = block[field.key] || '';
    }

    input.addEventListener('input', function () {
      if (field.key === 'items') {
        block[field.key] = fromMultiline(input.value);
      } else if (field.key === 'image_asset_id') {
        block[field.key] = input.value ? parseInt(input.value, 10) : '';
        if (block[field.key]) {
          block.image_url = '';
        }
      } else {
        block[field.key] = input.value;
        if (field.key === 'image_url' && input.value) {
          block.image_asset_id = '';
        }
      }
      onChange();
    });
    input.addEventListener('change', function () {
      if (field.key === 'items') {
        block[field.key] = fromMultiline(input.value);
      } else if (field.key === 'image_asset_id') {
        block[field.key] = input.value ? parseInt(input.value, 10) : '';
        if (block[field.key]) {
          block.image_url = '';
        }
      } else {
        block[field.key] = input.value;
        if (field.key === 'image_url' && input.value) {
          block.image_asset_id = '';
        }
      }
      onChange();
    });
    wrapper.appendChild(input);

    if (field.help) {
      var help = document.createElement('small');
      help.textContent = field.help;
      wrapper.appendChild(help);
    }

    return wrapper;
  }

  function previewHtml(block, libraries) {
    var align = block.align === 'center' ? 'center' : 'left';
    if (block.type === 'heading') {
      var tag = block.level === '1' ? 'h1' : (block.level === '3' ? 'h3' : 'h2');
      return '<' + tag + ' style="text-align:' + align + ';">' + escapeHtml(block.text) + '</' + tag + '>';
    }
    if (block.type === 'paragraph') {
      var size = block.style === 'lead' ? '18px' : (block.style === 'small' ? '14px' : '16px');
      return '<p style="text-align:' + align + ';font-size:' + size + ';line-height:1.7;">' + escapeHtml(block.text).replace(/\n/g, '<br>') + '</p>';
    }
    if (block.type === 'list') {
      return '<ul>' + (block.items || []).map(function (item) { return '<li>' + escapeHtml(item) + '</li>'; }).join('') + '</ul>';
    }
    if (block.type === 'image') {
      var image = resolvePreviewImage(block, libraries.imageAssetsById);
      if (!image.image_url) {
        return '<p>Image block</p>';
      }
      var caption = image.caption ? '<figcaption>' + escapeHtml(image.caption) + '</figcaption>' : '';
      return '<figure><img src="' + escapeHtml(image.image_url) + '" alt="' + escapeHtml(image.alt_text || '') + '">' + caption + '</figure>';
    }
    if (block.type === 'button') {
      return '<div class="preview-button preview-button--' + escapeHtml(block.style || 'primary') + '" style="text-align:' + align + ';"><a href="#">' + escapeHtml(block.text || 'Button') + '</a></div>';
    }
    if (block.type === 'quote') {
      var attribution = block.attribution ? '<div><strong>' + escapeHtml(block.attribution) + '</strong></div>' : '';
      return '<blockquote>' + escapeHtml(block.text || '').replace(/\n/g, '<br>') + attribution + '</blockquote>';
    }
    if (block.type === 'divider') {
      return '<hr style="border:none;border-top:1px solid rgba(255,255,255,0.16);">';
    }
    if (block.type === 'spacer') {
      var height = block.size === 'lg' ? 40 : (block.size === 'sm' ? 16 : 28);
      return '<div style="height:' + height + 'px"></div>';
    }
    return '';
  }

  function initEditor(container) {
    var targetId = container.getAttribute('data-target-id');
    var input = document.getElementById(targetId);
    if (!input) {
      return;
    }

    var imageAssets = parseJsonScript(container.getAttribute('data-assets-script-id'));
    var imageAssetsById = {};
    imageAssets.forEach(function (asset) {
      imageAssetsById[String(asset.id)] = asset;
    });
    var blockTemplates = parseJsonScript(container.getAttribute('data-templates-script-id'));
    var libraries = {
      imageAssets: imageAssets,
      imageAssetsById: imageAssetsById,
      blockTemplates: blockTemplates
    };

    var blocks;
    try {
      blocks = JSON.parse(input.value || '[]');
      if (!Array.isArray(blocks)) {
        blocks = [];
      }
    } catch (error) {
      blocks = [];
    }

    function syncData() {
      input.value = JSON.stringify(blocks);
    }

    function updatePreview() {
      var previewContent = container.querySelector('.newsletter-block-editor__preview-content');
      if (!previewContent) {
        return;
      }
      previewContent.innerHTML = blocks.map(function (block) { return previewHtml(block, libraries); }).join('');
    }

    function syncPreview() {
      syncData();
      updatePreview();
    }

    function syncStructure() {
      syncData();
      render();
    }

    function moveBlock(index, offset) {
      var target = index + offset;
      if (target < 0 || target >= blocks.length) {
        return;
      }
      var item = blocks[index];
      blocks.splice(index, 1);
      blocks.splice(target, 0, item);
      syncStructure();
    }

    function render() {
      container.innerHTML = '';

      var layout = document.createElement('div');
      layout.className = 'newsletter-block-editor__layout';

      var panel = document.createElement('div');
      panel.className = 'newsletter-block-editor__panel';

      var toolbar = document.createElement('div');
      toolbar.className = 'newsletter-block-editor__toolbar';
      Object.keys(BLOCK_TEMPLATES).forEach(function (blockType) {
        toolbar.appendChild(createButton('Add ' + BLOCK_LABELS[blockType], function () {
          blocks.push(BLOCK_TEMPLATES[blockType]());
          syncStructure();
        }));
      });
      panel.appendChild(toolbar);

      if (libraries.blockTemplates.length) {
        var templateBar = document.createElement('div');
        templateBar.className = 'newsletter-block-editor__template-bar';

        var templateSelect = document.createElement('select');
        templateSelect.className = 'newsletter-block-editor__template-select';
        var defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = 'Insert saved template';
        templateSelect.appendChild(defaultOption);

        libraries.blockTemplates.forEach(function (template) {
          var option = document.createElement('option');
          option.value = String(template.id);
          option.textContent = template.category ? (template.name + ' [' + template.category + ']') : template.name;
          templateSelect.appendChild(option);
        });

        var templateInsertButton = createButton('Insert template', function () {
          var selectedTemplate = null;
          libraries.blockTemplates.forEach(function (template) {
            if (String(template.id) === templateSelect.value) {
              selectedTemplate = template;
            }
          });
          if (!selectedTemplate) {
            return;
          }
          blocks = blocks.concat(deepClone(selectedTemplate.blocks || []));
          templateSelect.value = '';
          syncStructure();
        });

        templateBar.appendChild(templateSelect);
        templateBar.appendChild(templateInsertButton);
        panel.appendChild(templateBar);
      }

      var list = document.createElement('div');
      list.className = 'newsletter-block-editor__list';

      if (!blocks.length) {
        var empty = document.createElement('div');
        empty.className = 'newsletter-block-editor__empty';
        empty.textContent = 'No content blocks yet. Add a block to start composing the newsletter.';
        list.appendChild(empty);
      }

      blocks.forEach(function (block, index) {
        var blockNode = document.createElement('div');
        blockNode.className = 'newsletter-block-editor__block';

        var header = document.createElement('div');
        header.className = 'newsletter-block-editor__block-header';

        var titleWrap = document.createElement('div');
        titleWrap.className = 'newsletter-block-editor__block-title';

        var select = document.createElement('select');
        Object.keys(BLOCK_LABELS).forEach(function (blockType) {
          var option = document.createElement('option');
          option.value = blockType;
          option.textContent = BLOCK_LABELS[blockType];
          if (block.type === blockType) {
            option.selected = true;
          }
          select.appendChild(option);
        });
        select.addEventListener('change', function () {
          blocks[index] = BLOCK_TEMPLATES[select.value]();
          syncStructure();
        });
        titleWrap.appendChild(select);
        header.appendChild(titleWrap);

        var actions = document.createElement('div');
        actions.className = 'newsletter-block-editor__block-actions';
        actions.appendChild(createButton('Up', function () { moveBlock(index, -1); }));
        actions.appendChild(createButton('Down', function () { moveBlock(index, 1); }));
        actions.appendChild(createButton('Remove', function () {
          blocks.splice(index, 1);
          syncStructure();
        }));
        header.appendChild(actions);
        blockNode.appendChild(header);

        var fields = document.createElement('div');
        fields.className = 'newsletter-block-editor__fields';
        (BLOCK_FIELDS[block.type] || []).forEach(function (field) {
          fields.appendChild(renderField(block, field, syncPreview, libraries));
        });
        blockNode.appendChild(fields);
        list.appendChild(blockNode);
      });

      panel.appendChild(list);

      var preview = document.createElement('div');
      preview.className = 'newsletter-block-editor__preview';
      preview.innerHTML = '<div class="newsletter-block-editor__preview-title">Preview</div>' +
        '<div class="newsletter-block-editor__preview-shell">' +
        '<div class="newsletter-block-editor__preview-content">' +
        blocks.map(function (block) { return previewHtml(block, libraries); }).join('') +
        '</div></div>';

      layout.appendChild(panel);
      layout.appendChild(preview);
      container.appendChild(layout);
    }

    syncData();
    render();
  }

  document.addEventListener('DOMContentLoaded', function () {
    var editors = document.querySelectorAll('.newsletter-block-editor[data-target-id]');
    Array.prototype.forEach.call(editors, initEditor);
  });
})();