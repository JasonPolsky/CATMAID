/* -*- mode: espresso; espresso-indent-level: 2; indent-tabs-mode: nil -*- */
/* vim: set softtabstop=2 shiftwidth=2 tabstop=2 expandtab: */

(function (CATMAID) {

    /**
     * A simple bookmark creation and retrieval dialog.
     */
    var BookmarkDialog = function (mode, callback) {
      this.dialog = new CATMAID.OptionsDialog("Bookmarks");
      this.dialog.buttons = {'Cancel': undefined};

      var message;
      switch (mode) {
        case BookmarkDialog.MODES.MARK:
          message = "Press key to mark current location";
          break;
        case BookmarkDialog.MODES.SKELETON:
          message = "Press key to go to bookmarked skeleton";
          break;
        case BookmarkDialog.MODES.NODE:
          message = "Press key to go to bookmarked node";
          break;
      }
      message += " (ESC to cancel)";
      this.dialog.appendMessage(message);

      this.markerField = this.dialog.appendField('Marker', 'marker', '');
      $(this.dialog.dialog).find('label').css('width', '25%');
      $(this.dialog.dialog).find('label').css('display', 'inline-block');

      $(this.markerField).keypress((function (e) {
        if (e.keyCode !== $.ui.keyCode.ESCAPE &&
            e.keyCode !== $.ui.keyCode.ENTER) {
          if (mode === BookmarkDialog.MODES.MARK) {
            BookmarkDialog.mark(e.keyCode, e.key);
          } else {
            BookmarkDialog.goTo(e.keyCode, mode);
          }
        }

        this.destroy();
        return false;
      }).bind(this));

      var bookmarkEntries = $('<tbody>');
      BookmarkDialog.Bookmarks.forEach(function (bookmark, keyCode) {
        bookmarkEntries.append($('<tr>')
            .append($('<td>').text(bookmark.key))
            .append($('<td>').text(bookmark.skeletonID))
            .append($('<td>').text(bookmark.nodeID))
            .append($('<td>').text(bookmark.projectPosition.x))
            .append($('<td>').text(bookmark.projectPosition.y))
            .append($('<td>').text(bookmark.projectPosition.z))
            .append($('<td>').html('<span data-key="' + keyCode +
                '" class="ui-icon ui-icon-close action-remove" alt="Remove bookmark" title="Remove bookmark"></span>')));
      });
      $(this.dialog.dialog).append($('<table>')
          .append($('<thead><tr><th>Key</th><th>Skeleton</th><th>Node</th><th>x</th><th>y</th><th>z</th></tr></thead>'))
          .append(bookmarkEntries))
        .on('click', 'span.action-remove', this, function(event) {
          var dialogInstance = event.data;
          var key = $(this).data()['key'];
          BookmarkDialog.Bookmarks.delete(key);
          $(this).closest('div').find('input').focus();
          $(this).closest('tr').remove();
        });
    };

    BookmarkDialog.prototype = {};

    BookmarkDialog.MODES = Object.freeze({MARK: 0, SKELETON: 1, NODE: 2});

    /**
     * A map from bookmark keycodes to an object with at least `skeletonID`,
     * `nodeID` and `projectPosition` of the bookmarked location.
     * @type {Map}
     */
    BookmarkDialog.Bookmarks = new Map();

    /**
     * Mark the current location, node and skeleton in the bookmarks.
     *
     * @param  {number} keyCode      Emitted browser code for the mark key.
     * @param  {string} keyCharacter Display character for the mark key.
     */
    BookmarkDialog.mark = function (keyCode, keyCharacter) {
      var atnID = SkeletonAnnotations.getActiveNodeId();
      var atnPos = SkeletonAnnotations.getActiveNodePositionW();

      if (null === atnID) {
        atnPos = project.focusedStackViewer.projectCoordinates();
      }

      BookmarkDialog.Bookmarks.set(keyCode, {
        key: keyCharacter,
        nodeID: atnID,
        skeletonID: SkeletonAnnotations.getActiveSkeletonId(),
        projectPosition: atnPos
      });
    };

    /**
     * Go to a bookmark.
     *
     * @param  {number} keyCode      Emitted browser code for the mark key.
     * @param  {string} mode         Retrieval mode, from BookmarkDialog.MODES.
     * @return {Promise}             A promise succeeding after arriving at the
     *                               bookmark.
     */
    BookmarkDialog.goTo = function (keyCode, mode) {
      var bookmark = BookmarkDialog.Bookmarks.get(keyCode);

      if (!bookmark) {
        return Promise.reject();
      }

      if (mode === BookmarkDialog.MODES.SKELETON && bookmark.skeletonID) {
        return CATMAID.TracingTool.goToNearestInNeuronOrSkeleton('skeleton', bookmark.skeletonID);
      } else if (bookmark.nodeID) {
        return SkeletonAnnotations.staticMoveToAndSelectNode(bookmark.nodeID)
            .then(function (nodes) {
              var pos = SkeletonAnnotations.getActiveNodePositionW();
              if (pos.x !== bookmark.projectPosition.x ||
                  pos.y !== bookmark.projectPosition.y ||
                  pos.z !== bookmark.projectPosition.z) {
                CATMAID.info('This node has moved since it was bookmarked.');
              }

              var node = nodes[0];
              if (node.id && node.skeleton_id !== bookmark.skeletonID) {
                CATMAID.info('This node has changed skeletons since it was bookmarked.');
              }
            });
      } else {
        project.deselectActiveNode();
        return SkeletonAnnotations.staticMoveTo(bookmark.projectPosition.z,
                                         bookmark.projectPosition.y,
                                         bookmark.projectPosition.x);
      }
    };

    /**
     * Displays the bookmark dialog.
     */
    BookmarkDialog.prototype.show = function () {
      this.dialog.show('350', 'auto', true);
    };

    BookmarkDialog.prototype.destroy = function () {
      $(this.dialog.dialog).dialog('destroy');
    };

    // Make dialog available in CATMAID namespace
    CATMAID.BookmarkDialog = BookmarkDialog;

})(CATMAID);

