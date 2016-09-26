/* -*- mode: espresso; espresso-indent-level: 2; indent-tabs-mode: nil -*- */
/* vim: set softtabstop=2 shiftwidth=2 tabstop=2 expandtab: */

(function(CATMAID) {

  "use strict";

  var ConnectorTable = function(optionalSkid)
  {
    this.widgetID = this.registerInstance();

    /** Pointer to the existing instance of table. */
    this.connectorTable = null;

    var self = this;
    var asInitValsSyn = [];
    var skeletonID = optionalSkid ? optionalSkid : -1;
    var possibleLengths = CATMAID.pageLengthOptions;
    var possibleLengthsLabels = CATMAID.pageLengthLabels;

    this.updateConnectorTable = function() {
      self.setSkeleton( -1 );
      self.connectorTable.fnClearTable( 0 );
      self.connectorTable.fnDraw();
    };

    this.refreshConnectorTable = function() {
      self.connectorTable.fnClearTable( 0 );
      self.connectorTable.fnDraw();
    };

    this.setSkeleton = function( skeleton_id ) {
      skeletonID = skeleton_id;
    };

    this.getSkeletonId = function() {
      return skeletonID;
    };

    this.init = function (pid) {
      var widgetID = this.widgetID;
      var tableid = '#connectortable' + widgetID;

      self.connectorTable = $(tableid).dataTable(
        {
          "bDestroy": true,
          "sDom": '<"H"lr>t<"F"ip>',
          "bProcessing": true,
          "bServerSide": true,
          "bAutoWidth": false,
          "iDisplayLength": possibleLengths[0],
          "sAjaxSource": django_url + project.id + '/connector/table/list',
          "fnServerData": function (sSource, aoData, fnCallback) {

            if( skeletonID === -1 ) {
              skeletonID = SkeletonAnnotations.getActiveSkeletonId();
            }

            if (!skeletonID) {
              CATMAID.msg('BEWARE', 'You need to activate a treenode to display ' +
                  'the connector table of its skeleton.');
              skeletonID = 0;
            }

            aoData.push({
              "name": "relation_type",
              "value" : $('#connector_relation_type' + widgetID + ' :selected').attr("value")
            });
            aoData.push({
              "name" : "pid",
              "value" : pid
            });
            aoData.push({
              "name" : "skeleton_id",
              "value" : skeletonID
            });

            $.ajax({
              "dataType": 'json',
              "cache": false,
              "type": "POST",
              "url": sSource,
              "data": aoData,
              "success": fnCallback
            });

          },
          "aLengthMenu": [
            possibleLengths,
            possibleLengthsLabels
          ],
          "bJQueryUI": true,
          "aoColumns": [
            {
              "bSearchable": false,
              "bSortable": true
            }, // connector id
            {
              "sClass": "center",
              "bSearchable": false
            }, // other skeleton id
            {
              "sClass": "center",
              "bSearchable": false
            }, // x
            {
              "sClass": "center",
              "bSearchable": false
            }, // y
            {
              "sClass": "center",
              "bSearchable": false
            }, // z
            {
              "sClass": "center",
              "bSearchable": false,
              "bSortable": true,
              data: 4,
              render: function(data, type, row, meta) {
                return project.focusedStackViewer.primaryStack.projectToStackZ(row[4], row[3], row[2]);
              },
            }, // section index
            {
              "bSearchable": false,
              "bSortable": true,
              data: 5,
            }, // connectortags
            {
              "bSearchable": false,
              "bSortable": true,
              data: 6,
            }, // confidence
            {
              "bSearchable": false,
              "bSortable": true,
              data: 7,
            }, // target confidence
            {
              "bSearchable": false,
              "bSortable": true,
              data: 8,
            }, // number of nodes
            {
              "bVisible": true,
              "bSortable": true,
              data: 9,
            }, // username
            {
              "bSearchable": false,
              "bSortable": true,
              "bVisible": true,
              data: 10,
            }, // treenodes
            {
              "bSearchable": false,
              "bSortable": true,
              "bVisible": true,
              data: 11,
              render: function(data, type, row, meta) {
                var d = new Date(data);
                return d.getFullYear() + '-' + (d.getMonth() + 1) + '-' + d.getDate()
                    + ' ' + d.getHours() + ':' + d.getMinutes();
              }
            } // last modified
          ]
        });

      $(tableid + " tfoot input").keyup(function () { /* Filter on the column (the index) of this element */
        self.connectorTable.fnFilter(this.value, $("tfoot input").index(this));
      });

      /*
       * Support functions to provide a little bit of 'user friendlyness' to the textboxes in
       * the footer
       */
      $(tableid + " tfoot input").each(function (i) {
        asInitValsSyn[i] = this.value;
      });

      $(tableid + " tfoot input").focus(function () {
        if (this.className == "search_init") {
          this.className = "";
          this.value = "";
        }
      });

      $(tableid + " tfoot input").blur(function (i) {
        if (this.value == "") { // jshint ignore:line
          this.className = "search_init";
          this.value = asInitValsSyn[$("tfoot input").index(this)];
        }
      });

      $(tableid + " tbody").on('dblclick', 'td', function () {
        // Allow clicking on the connector ID (column 0) to select it rather
        // than the target treenode.
        if ($(this).index() !== 0) return;
        var idToActivate = self.connectorTable.fnGetData(this);

        SkeletonAnnotations.staticMoveToAndSelectNode(idToActivate);

        return false;
      });

      $(tableid + " tbody").on('dblclick', 'tr', function () {
        var idToActivate, skeletonID;
        var aData = self.connectorTable.fnGetData(this);
        // retrieve coordinates and moveTo
        var x = parseFloat(aData[2]);
        var y = parseFloat(aData[3]);
        var z = parseFloat(aData[4]);

        // If there is a partner treenode, activate that - otherwise
        // activate the connector itself:
        if (aData[10]) {
          idToActivate = parseInt(aData[10], 10);
          skeletonID = parseInt(aData[1], 10);
        } else {
          idToActivate = parseInt(aData[0], 10);
          skeletonID = null;
        }

        SkeletonAnnotations.staticMoveTo(z, y, x,
          function () {
            SkeletonAnnotations.staticSelectNode(idToActivate, skeletonID);
          });
      });

      $('#connector_relation_type' + widgetID).change(function() {
        var numberOfNodesText, otherSkeletonText, otherTreenodeText, adjective;
        self.connectorTable.fnDraw();
        if ($('#connector_relation_type' + widgetID + ' :selected').attr("value") === "0") {
          adjective = "source";
        } else {
          adjective = "target";
        }
        numberOfNodesText = "# nodes in " + adjective + " skeleton";
        otherSkeletonText = adjective + " skeleton ID";
        otherTreenodeText = adjective + " treenode ID";
        $("#connector_nr_nodes_top" + widgetID).text(numberOfNodesText);
        $("#connector_nr_nodes_bottom" + widgetID).text(numberOfNodesText);
        $("#other_skeleton_top" + widgetID).text(otherSkeletonText);
        $("#other_skeleton_bottom" + widgetID).text(otherSkeletonText);
        $("#other_treenode_top" + widgetID).text(otherTreenodeText);
        $("#other_treenode_bottom" + widgetID).text(otherTreenodeText);
      });

    };
  };

  ConnectorTable.prototype = {};
  $.extend(ConnectorTable.prototype, new InstanceRegistry());

  ConnectorTable.prototype.getName = function() {
    return "Connector table " + this.widgetID;
  };

  ConnectorTable.prototype.destroy = function() {
    this.unregisterInstance();
  };

  /**
   * Export the currently displayed table as CSV.
   */
  ConnectorTable.prototype.exportCSV = function() {
    if (!this.connectorTable) return;
    var relation = $('#connector_relation_type' + this.widgetID + ' :selected').val();
    var table = this.connectorTable.DataTable();
    var header = table.columns().header().map(function(h) {
      return $(h).text();
    });
    var connectorRows = table.rows({"order": "current"}).data();
    var csv = header.join(',') + '\n' + connectorRows.map(function(row) {
      return row.join(',');
    }).join('\n');
    var blob = new Blob([csv], {type: 'text/plain'});
    saveAs(blob, "catmaid-connectors-" + relation + "-skeleton-" +
        this.getSkeletonId() + ".csv");
  };

  // Export widget
  CATMAID.ConnectorTable = ConnectorTable;

})(CATMAID);
