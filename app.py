# Copyright (c) 2015 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
Geometry Output node App for use with Toolkit's Houdini engine.
"""

import sgtk


class TkGeometryNodeApp(sgtk.platform.Application):
    """The Geometry Output Node."""

    def init_app(self):
        """Initialize the app."""

        tk_houdini_geometry = self.import_module("tk_houdini_geometrynode")
        self.handler = tk_houdini_geometry.TkGeometryNodeHandler(self)

    def convert_to_regular_geometry_nodes(self):
        """Convert Toolkit Geometry nodes to regular Geometry nodes.
        
        Convert all Toolkit Geometry nodes found in the current script to
        regular Geometry nodes. Additional Toolkit information will be stored in
        user data named 'tk_*'

        Example usage::

        >>> import sgtk
        >>> eng = sgtk.platform.current_engine()
        >>> app = eng.apps["tk-houdini-geometrynode"]
        >>> app.convert_to_regular_geometry_nodes()

        """

        self.log_debug(
            "Converting Toolkit Geometry nodes to built-in Geometry nodes.")
        tk_houdini_geometry = self.import_module("tk_houdini_geometrynode")
        tk_houdini_geometry.TkGeometryNodeHandler.\
            convert_to_regular_geometry_nodes(self)

    def convert_back_to_tk_geometry_nodes(self):
        """Convert regular Geometry nodes back to Tooklit Geometry nodes.
        
        Convert any regular Geometry nodes that were previously converted
        from Tooklit Geometry nodes back into Toolkit Geometry nodes.

        Example usage::

        >>> import sgtk
        >>> eng = sgtk.platform.current_engine()
        >>> app = eng.apps["tk-houdini-geometrynode"]
        >>> app.convert_back_to_tk_geometry_nodes()

        """

        self.log_debug(
            "Converting built-in Geometry nodes back to Toolkit Geometry nodes.")
        tk_houdini_geometry = self.import_module("tk_houdini_geometrynode")
        tk_houdini_geometry.TkGeometryNodeHandler.\
            convert_back_to_tk_geometry_nodes(self)

    def get_nodes(self):
        """
        Returns a list of hou.node objects for each tk geometry node.

        Example usage::

        >>> import sgtk
        >>> eng = sgtk.platform.current_engine()
        >>> app = eng.apps["tk-houdini-geometrynode"]
        >>> tk_geometry_nodes = app.get_nodes()
        """

        self.log_debug("Retrieving tk-houdini-geometry nodes...")
        tk_houdini_geometry = self.import_module("tk_houdini_geometrynode")
        nodes = tk_houdini_geometry.TkGeometryNodeHandler.\
            get_all_tk_geometry_nodes()
        self.log_debug("Found %s tk-houdini-geometry nodes." % (len(nodes),))
        return nodes

    def get_output_path(self, node):
        """
        Returns the evaluated output path for the supplied node.

        Example usage::

        >>> import sgtk
        >>> eng = sgtk.platform.current_engine()
        >>> app = eng.apps["tk-houdini-geometrynode"]
        >>> output_path = app.get_output_path(tk_geometry_node)
        """

        self.log_debug("Retrieving output path for %s" % (node,))
        tk_houdini_geometry = self.import_module("tk_houdini_geometrynode")
        output_path = tk_houdini_geometry.TkGeometryNodeHandler.\
            get_output_path(node)
        self.log_debug("Retrieved output path: %s" % (output_path,))
        return output_path

    def get_work_file_template(self):
        """
        Returns the configured work file template for the app.
        """

        return self.get_template("work_file_template")


    def get_publish_name(self, node):

        return self.handler.compute_publish_name(node)