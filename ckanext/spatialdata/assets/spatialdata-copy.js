/* Copy the value of a target input to the clipboard.
 *
 * Usage:
 *   <input id="my-input" value="...">
 *   <button data-module="spatialdata-copy" data-module-target="#my-input">
 *     <i class="fa fa-copy" aria-hidden="true"></i>
 *     <span class="visually-hidden">Copy</span>
 *     <span class="visually-hidden" role="status" data-copy-status></span>
 *   </button>
 *
 * Also selects the input's text when it gets focus.
 */
ckan.module("spatialdata-copy", function ($) {
  return {
    options: {
      target: null,
      copiedText: "Copied to clipboard",
      failedText: "Could not copy. Select the text and copy it manually.",
    },

    initialize: function () {
      $.proxyAll(this, /_on/);
      this.input = $(this.options.target);
      this.icon = this.el.find(".fa");
      this.status = this.el.find("[data-copy-status]");
      this.el.on("click", this._onClick);
      this.input.on("focus", function () { this.select(); });
    },

    _onClick: function () {
      var text = this.input.val();
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(this._onCopied, this._onFailed);
      } else {
        // http:// pages have no Clipboard API; fall back to execCommand
        this.input.trigger("focus").get(0).select();
        try {
          document.execCommand("copy") ? this._onCopied() : this._onFailed();
        } catch (e) {
          this._onFailed();
        }
      }
    },

    _onCopied: function () {
      this._flash("fa-check", this._(this.options.copiedText));
    },

    _onFailed: function () {
      this._flash("fa-times", this._(this.options.failedText));
    },

    _flash: function (iconClass, message) {
      var icon = this.icon;
      var status = this.status;
      icon.removeClass("fa-copy").addClass(iconClass);
      status.text(message);
      this.el.attr("title", message);
      clearTimeout(this._timer);
      this._timer = setTimeout(function () {
        icon.removeClass(iconClass).addClass("fa-copy");
        status.text("");
      }, 2000);
    },
  };
});
