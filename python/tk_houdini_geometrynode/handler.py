# Copyright (c) 2015 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

# built-ins
import base64
import os
import sys
import zlib
import shutil

try:
   import cPickle as pickle
except:
   import pickle

# houdini
import hou
import _alembic_hom_extensions as abc

# import pyseq
import pyseq

# toolkit
import sgtk


class TkGeometryNodeHandler(object):
    """Handle Tk Geometry node operations and callbacks."""


    ############################################################################
    # Class data

    HOU_ROP_GEOMETRY_TYPE = "geometry"
    """Houdini type for geometry rops."""

    HOU_SOP_GEOMETRY_TYPE = "rop_geometry"
    """Houdini type for geometry sops."""
    # this is correct. the houdini internal rop_geometry is a sop.

    NODE_OUTPUT_PATH_PARM = "sopoutput"
    """The name of the output path parameter on the node."""

    TK_GEOMETRY_NODE_TYPE = "sgtk_geometry"
    """The class of node as defined in Houdini for the Geometry nodes."""

    TK_OUTPUT_CONNECTIONS_KEY = "tk_output_connections"
    """The key in the user data that stores the save output connections."""

    TK_OUTPUT_CONNECTION_CODEC = "sgtk-01"
    """The encode/decode scheme currently being used."""

    TK_OUTPUT_CONNECTION_CODECS = {
        "sgtk-01": {
            'encode': lambda data: \
                base64.b64encode(zlib.compress(pickle.dumps(data))),
            'decode': lambda data_str: \
                pickle.loads(zlib.decompress(base64.b64decode(data_str))),
        },
    }
    """Encode/decode schemes. To support backward compatibility if changes."""
    # codec names should not include a ":"

    TK_OUTPUT_PROFILE_PARM = "output_profile"
    """The name of the parameter that stores the current output profile."""

    TK_OUTPUT_PROFILE_NAME_KEY = "tk_output_profile_name"
    """The key in the user data that stores the output profile name."""

    TK_USD_PRIM_PREFIX_PATH = "prim_prefix_path"
    # the prefix of the prim path

    TK_USD_PRIM_PATH = "prim_path"

    ############################################################################
    # Class methods

    @classmethod
    def convert_back_to_tk_geometry_nodes(cls, app):
        """Convert Geometry nodes back to Toolkit Geometry nodes.

        :param app: The calling Toolkit Application

        Note: only converts nodes that had previously been Toolkit Geometry
        nodes.

        """

        # get all rop/sop geometry nodes in the session
        geometry_nodes = []
        geometry_nodes.extend(hou.nodeType(hou.sopNodeTypeCategory(),
            cls.HOU_SOP_GEOMETRY_TYPE).instances())
        geometry_nodes.extend(hou.nodeType(hou.ropNodeTypeCategory(),
            cls.HOU_ROP_GEOMETRY_TYPE).instances())

        if not geometry_nodes:
            app.log_debug("No Geometry Nodes found for conversion.")
            return

        # the tk node type we'll be converting to
        tk_node_type = TkGeometryNodeHandler.TK_GEOMETRY_NODE_TYPE

        # iterate over all the geometry nodes and attempt to convert them
        for geometry_node in geometry_nodes:

            # get the user data dictionary stored on the node
            user_dict = geometry_node.userDataDict()

            # get the output_profile from the dictionary
            tk_output_profile_name = user_dict.get(
                cls.TK_OUTPUT_PROFILE_NAME_KEY)

            if not tk_output_profile_name:
                app.log_warning(
                    "Geometry node '%s' does not have an output profile name. "
                    "Can't convert to Tk Geometry node. Continuing." %
                    (geometry_node.name(),)
                )
                continue

            # create a new, Toolkit Geometry node:
            tk_geometry_node = geometry_node.parent().createNode(tk_node_type)

            # find the index of the stored name on the new tk geometry node
            # and set that item in the menu.
            try:
                output_profile_parm = tk_geometry_node.parm(
                    TkGeometryNodeHandler.TK_OUTPUT_PROFILE_PARM)
                output_profile_index = output_profile_parm.menuLabels().index(
                    tk_output_profile_name)
                output_profile_parm.set(output_profile_index)
            except ValueError:
                app.log_warning("No output profile found named: %s" % 
                    (tk_output_profile_name,))

            # copy over all parameter values except the output path 
            _copy_parm_values(geometry_node, tk_geometry_node,
                excludes=[cls.NODE_OUTPUT_PATH_PARM])

            # copy the inputs and move the outputs
            _copy_inputs(geometry_node, tk_geometry_node)

            # determine the built-in operator type
            if geometry_node.type().name() == cls.HOU_SOP_GEOMETRY_TYPE:
                _restore_outputs_from_user_data(geometry_node, tk_geometry_node)
            elif geometry_node.type().name() == cls.HOU_ROP_GEOMETRY_TYPE:
                _move_outputs(geometry_node, tk_geometry_node)

            # make the new node the same color. the profile will set a color, 
            # but do this just in case the user changed the color manually
            # prior to the conversion.
            tk_geometry_node.setColor(geometry_node.color())

            # remember the name and position of the original geometry node
            geometry_node_name = geometry_node.name()
            geometry_node_pos = geometry_node.position()

            # destroy the original geometry node
            geometry_node.destroy()

            # name and reposition the new, regular geometry node to match the
            # original
            tk_geometry_node.setName(geometry_node_name)
            tk_geometry_node.setPosition(geometry_node_pos)

            app.log_debug("Converted: Geometry node '%s' to TK Geometry node."
                % (geometry_node_name,))

    @classmethod
    def convert_to_regular_geometry_nodes(cls, app):
        """Convert Toolkit Geometry nodes to regular Geometry nodes.

        :param app: The calling Toolkit Application

        """

        tk_node_type = TkGeometryNodeHandler.TK_GEOMETRY_NODE_TYPE

        # determine the surface operator type for this class of node
        sop_types = hou.sopNodeTypeCategory().nodeTypes()
        sop_type = sop_types[tk_node_type]

        # determine the render operator type for this class of node
        rop_types = hou.ropNodeTypeCategory().nodeTypes()
        rop_type = rop_types[tk_node_type]

        # get all instances of tk geometry rop/sop nodes
        tk_geometry_nodes = []
        tk_geometry_nodes.extend(
            hou.nodeType(hou.sopNodeTypeCategory(), tk_node_type).instances())
        tk_geometry_nodes.extend(
            hou.nodeType(hou.ropNodeTypeCategory(), tk_node_type).instances())

        if not tk_geometry_nodes:
            app.log_debug("No Toolkit Geometry Nodes found for conversion.")
            return

        # iterate over all the tk geometry nodes and attempt to convert them
        for tk_geometry_node in tk_geometry_nodes:

            # determine the corresponding, built-in operator type
            if tk_geometry_node.type() == sop_type:
                geometry_operator = cls.HOU_SOP_GEOMETRY_TYPE
            elif tk_geometry_node.type() == rop_type:
                geometry_operator = cls.HOU_ROP_GEOMETRY_TYPE
            else:
                app.log_warning("Unknown type for node '%s': %s'" %
                    (tk_geometry_node.name(), tk_geometry_node.type()))
                continue

            # create a new, regular Geometry node
            geometry_node = tk_geometry_node.parent().createNode(geometry_operator)

            # copy the file parms value to the new node
            filename = _get_output_menu_label(
                tk_geometry_node.parm(cls.NODE_OUTPUT_PATH_PARM))
            geometry_node.parm(cls.NODE_OUTPUT_PATH_PARM).set(filename)

            # copy across knob values
            _copy_parm_values(tk_geometry_node, geometry_node,
                excludes=[cls.NODE_OUTPUT_PATH_PARM])

            # store the geometry output profile name in the user data so that we
            # can retrieve it later.
            output_profile_parm = tk_geometry_node.parm(
                cls.TK_OUTPUT_PROFILE_PARM)
            tk_output_profile_name = \
                output_profile_parm.menuLabels()[output_profile_parm.eval()]
            geometry_node.setUserData(cls.TK_OUTPUT_PROFILE_NAME_KEY,
                tk_output_profile_name)

            # copy the inputs and move the outputs
            _copy_inputs(tk_geometry_node, geometry_node)
            if geometry_operator == cls.HOU_SOP_GEOMETRY_TYPE:
                _save_outputs_to_user_data(tk_geometry_node, geometry_node)
            elif geometry_operator == cls.HOU_ROP_GEOMETRY_TYPE:
                _move_outputs(tk_geometry_node, geometry_node)

            # make the new node the same color
            geometry_node.setColor(tk_geometry_node.color())

            # remember the name and position of the original tk geometry node
            tk_geometry_node_name = tk_geometry_node.name()
            tk_geometry_node_pos = tk_geometry_node.position()

            # destroy the original tk geometry node
            tk_geometry_node.destroy()

            # name and reposition the new, regular geometry node to match the
            # original
            geometry_node.setName(tk_geometry_node_name)
            geometry_node.setPosition(tk_geometry_node_pos)

            app.log_debug("Converted: Tk Geometry node '%s' to Geometry node."
                % (tk_geometry_node_name,))

    @classmethod
    def get_all_tk_geometry_nodes(cls):
        """
        Returns a list of all tk-houdini-geometrynode instances in the current
        session.
        """

        tk_node_type = TkGeometryNodeHandler.TK_GEOMETRY_NODE_TYPE

        return hou.nodeType(hou.ropNodeTypeCategory(), tk_node_type).instances()

    @classmethod
    def get_output_path(cls, node):
        """
        Returns the evaluated output path for the supplied node.
        """

        output_parm = node.parm(cls.NODE_OUTPUT_PATH_PARM)
        output_path = output_parm.evalAsString()
        output_path = output_path.replace("$F4", "%04d")


        return output_path


    ############################################################################
    # Instance methods

    def __init__(self, app):
        """Initialize the handler.
        
        :params app: The application instance. 
        
        """

        # keep a reference to the app for easy access to templates, settings,
        # logging methods, tank, context, etc.
        self._app = app

        # get and cache the list of profiles defined in the settings
        self._output_profiles = {}
        for output_profile in self._app.get_setting("output_profiles", []):
            output_profile_name = output_profile["name"]

            if output_profile_name in self._output_profiles:
                self._app.log_warning(
                    "Found multiple output profiles named '%s' for the "
                    "Tk Geometry node! Only the first one will be available." %
                    (output_profile_name,)
                )
                continue

            self._output_profiles[output_profile_name] = output_profile
            self._app.log_debug("Caching geometry output profile: '%s'" %
                (output_profile_name,))


    ############################################################################
    # methods and callbacks executed via the OTLs

    # copy the render path for the current node to the clipboard
    def copy_path_to_clipboard(self):
        render_path = self._get_render_path(hou.pwd())
        render_path = render_path.replace('/', os.sep)
        hou.ui.copyTextToClipboard(render_path)

        self._app.log_debug(
            "Copied render path to clipboard: %s" % (render_path,))

    # create an Geometry node, set the path to the output path of current node
    def create_geometry_node(self):
        current_node = hou.pwd()
        output_path_parm = current_node.parm(self.NODE_OUTPUT_PATH_PARM)
        geometry_node_name = 'geometry_' + current_node.name()

        # create the geometry node and set the filename parm
        geometry_node = current_node.parent().createNode(
            self.HOU_SOP_GEOMETRY_TYPE)
        geometry_node.parm(self.NODE_OUTPUT_PATH_PARM).set(
            output_path_parm.menuLabels()[output_path_parm.eval()])
        geometry_node.setName(geometry_node_name, unique_name=True)

        # move it away from the origin
        geometry_node.moveToGoodPosition()

    # get labels for all tk-houdini-geometry node output profiles
    def get_output_profile_menu_labels(self):
        menu_labels = []
        for count, output_profile_name in enumerate(self._output_profiles):
            menu_labels.extend([count, output_profile_name])

        return menu_labels

    # returns a list of menu items for the current node
    def get_output_path_menu_items(self):
        current_node = hou.pwd()

        # attempt to compute the output path and add it as an item in the menu
        try:
            path = self._compute_output_path(current_node)
            menu = [path, path]
        except sgtk.TankError as e:
            error_msg = ("Unable to construct the output path menu items: " 
                         "%s - %s" % (current_node.name(), e))
            self._app.log_error(error_msg)
            menu_str = "ERROR: %s" % error_msg
            menu = [menu_str, menu_str]

        if hou.isUIAvailable():
            current_node.parm('sopoutput_child').set(path)

        return menu

    # apply the selected profile in the session
    def set_profile(self, node=None):
        if not node:
            node = hou.pwd()

        output_profile = self._get_output_profile(node)

        self._app.log_debug("Applying tk geometry node profile: %s" %
            (output_profile["name"],))

        # apply the supplied settings to the node
        settings = output_profile["settings"]
        if settings:
            self._app.log_debug('Populating format settings: %s' % 
                (settings,))
            node.setParms(settings)

        # set the node color
        color = output_profile["color"]
        if color:
            node.setColor(hou.Color(color))

        self.refresh_output_path(node)

    # refresh the output profile path
    def refresh_output_path(self, node):
        output_path_parm = node.parm(self.NODE_OUTPUT_PATH_PARM)
        output_path_parm.set(output_path_parm.eval())

        self.check_seq(node)

    # open a file browser showing the render path of the current node
    def show_in_fs(self):
        # retrieve the calling node
        current_node = hou.pwd()
        if not current_node:
            return

        render_dir = None

        # first, try to just use the current cached path:
        render_path = self._get_render_path(current_node)

        if render_path:
            # the above method returns houdini style slashes, so ensure these
            # are pointing correctly
            render_path = render_path.replace("/", os.path.sep)

            dir_name = os.path.dirname(render_path)
            if os.path.exists(dir_name):
                render_dir = dir_name

        if not render_dir:
            # render directory doesn't exist so try using location
            # of rendered frames instead:
            rendered_files = self._get_rendered_files(current_node)

            if not rendered_files:
                msg = ("Unable to find rendered files for node '%s'." 
                       % (current_node,))
                self._app.log_error(msg)
                hou.ui.displayMessage(msg)
                return
            else:
                render_dir = os.path.dirname(rendered_files[0])

        # if we have a valid render path then show it:
        if render_dir:
            # TODO: move to utility method in core
            system = sys.platform

            # run the app
            if system == "linux2":
                cmd = "xdg-open \"%s\"" % render_dir
            elif system == "darwin":
                cmd = "open '%s'" % render_dir
            elif system == "win32":
                cmd = "cmd.exe /C start \"Folder\" \"%s\"" % render_dir
            else:
                msg = "Platform '%s' is not supported." % (system,)
                self._app.log_error(msg)
                hou.ui.displayMessage(msg)

            self._app.log_debug("Executing command:\n '%s'" % (cmd,))
            exit_code = os.system(cmd)
            if exit_code != 0:
                msg = "Failed to launch '%s'!" % (cmd,)
                hou.ui.displayMessage(msg)

    # called when the node is created.
    def setup_node(self, node):
        # apply the default profile
        self.set_profile(node)

        # set default range attributes
        node.parm('trange').set('normal')
        node.parm('trange').pressButton()

        if hou.applicationVersion()[0] >= 18:
            node.parm('f1').setExpression('$NOZSTART', hou.exprLanguage.Hscript)
            node.parm('f2').setExpression('$NOZEND', hou.exprLanguage.Hscript)
        else:
            node.parm('f1').set(hou.expandString('$FSTART'))
            node.parm('f2').set(hou.expandString('$FEND'))

        # enable auto versioning
        node.parm('auto_ver').set(1)

        self.reset_usd_prim_path(node)

        try:
            self._app.log_metric("Create", log_version=True)
        except:
            # ingore any errors. ex: metrics logging not supported
            pass


    def reset_usd_prim_path(self, node):

        prim_prefix_path = node.parm(self.TK_USD_PRIM_PREFIX_PATH).eval()
        out_node_name = node.name()

        prim_path = "{}/{}".format(prim_prefix_path, out_node_name)

        prim_path_parm = node.parm(self.TK_USD_PRIM_PATH)
        prim_path_parm.set(prim_path)


    # write backup file
    def create_backup_file(self, node):
        backup_path = self._compute_backup_output_path(node)

        # Create dir if it doesn't exist
        backup_dir_path = os.path.dirname(backup_path)
        if not os.path.exists(backup_dir_path):
            os.makedirs(backup_dir_path)

        # write backup hip
        hou.hipFile.save(file_name=None, save_to_recent_files=True)

        shutil.copy2(hou.hipFile.path(), backup_path)
        self._app.log_debug("Created backup file for %s" % node.name())

    def get_backup_file(self, node):
        backup_path = self._compute_backup_output_path(node)

        # check if backup file exists
        if os.path.exists(backup_path):
            return backup_path
        else:
            self._app.log_warning("Could not find backup hip file for %s" % node.path())

    def auto_publish(self, node):
        # cache that we are publishing
        cache_path = self._compute_output_path(node)

        # check if it already exists
        publishes = sgtk.util.find_publish(self._app.sgtk, [cache_path])
        if len(publishes.keys()) == 0:
            # get caches in scene, same as in tk-multi-breakdown
            refs = []

            for n in hou.node("/obj").allSubChildren(recurse_in_locked_nodes=False):
                hou_path = None
                node_type = n.type().name()
                if node_type == "alembicarchive":
                    hou_path = n.parm("fileName").eval().replace("/", os.path.sep)
                elif node_type == "abc_cam":
                    hou_path = n.parm("abcFile").eval().replace("/", os.path.sep)
                elif node_type == "sgtk_file" and n.parm('mode').evalAsString() == 'file':
                    hou_path = n.parm("file").eval().replace("/", os.path.sep)
                elif node_type == 'arnold_procedural':
                    hou_path = n.parm("ar_filename").eval().replace("/", os.path.sep)

                if hou_path:
                    refs.append(hou_path)

            # get current version
            version = node.parm('ver').evalAsInt()

            # Publish backup hip file
            backup_path = self._compute_backup_output_path(node)
            sgtk.util.register_publish(self._app.sgtk, self._app.context, backup_path, self._getNodeName(node), published_file_type="Backup File", version_number=version, dependency_paths=refs, created_by=self._app.context.user)

            # Publish cache
            # copied from tk-multi-publish2 collector file in shotgun config
            type_parm = node.parm('types')
            cache_type = type_parm.menuLabels()[type_parm.evalAsInt()]

            file_type_name = None
            if cache_type == 'bgeo.sc':
                file_type_name = "Bgeo Cache"
            elif cache_type == 'abc':
                file_type_name = "Alembic Cache"
            elif cache_type == 'exr':
                file_type_name = "Texture"
            else:
                file_type_name = "{} Cache".format(cache_type.title())

            if file_type_name:
                sgtk.util.register_publish(self._app.sgtk, self._app.context, cache_path, self._getNodeName(node), published_file_type=file_type_name, version_number=version, dependency_paths=[backup_path], created_by=self._app.context.user)
            else:
                self._app.log_error('Could not find the cache_type in auto_publish function!')
        else:
            self._app.log_info('Trying to register cache that already exists!')

    def auto_version(self, node):
        # get relevant fields from the current file path
        work_file_fields = self._get_hipfile_fields()

        output_profile = self._get_output_profile(node)
        output_cache_template = self._app.get_template_by_name(
            output_profile["output_cache_template"])

        # Get the type of output
        type_parm = node.parm('types')
        extension = type_parm.menuLabels()[type_parm.evalAsInt()]

        fields = {
            "name": work_file_fields.get("name", None),
            "node": self._getNodeName(node),
            "SEQ": "FORMAT: $F",
            "ext": extension
        }

        fields.update(self._app.context.as_template_fields(
            output_cache_template))

        max_version = 0
        for caches in self._app.sgtk.abstract_paths_from_template(output_cache_template, fields):
            fields = output_cache_template.get_fields(caches)
            if fields['version'] > max_version:
                max_version = fields['version']
        
        node.parm('ver').set(max_version + 1)

        # Create folder to 'reserve' cache version
        path = self._compute_output_path(node)

        if path:
            dir_path = os.path.dirname(path)
            
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)

    def check_seq(self, node):
        path = self._compute_output_path(node)
        node_color = hou.Color((0, 0.8, 0))

        return_str = None
        if '$F4' in path:
            path = path.replace('$F4', '*')
            sequences = pyseq.get_sequences(path)

            if len(sequences) == 1:
                seq = sequences[0]

                if seq:
                    if seq.missing():
                        return_str = '[%s-%s], missing %s' % (seq.format('%s'), seq.format('%e'), seq.format('%M'))
                    else:
                        return_str = seq.format('%R')

                    node_color = hou.Color((0.8, 0, 0))
                else:
                    return_str = 'Invalid Sequence Object!'
            else:
                return_str = 'No or multiple sequences detected!'
        elif path.split('.')[-1] == 'abc':
            if os.path.exists(path):
                abcRange = abc.alembicTimeRange(path)
                        
                if abcRange:
                    return_str = '[%s-%s] - ABC Archive' % (int(abcRange[0] * hou.fps()), int(abcRange[1] * hou.fps()))
                else:
                    return_str = 'Single Abc'
                
                node_color = hou.Color((0.8, 0, 0))
            else:
                return_str = 'No Cache!'
        else:
            if os.path.exists(path):
                return_str = 'Single Frame'

                node_color = hou.Color((0.8, 0, 0))
            else:
                return_str = 'No Cache!'

        # update shotgun files node as well
        for file_node in node.dependents(include_children=False):
            if file_node.type().name() == 'sgtk_file' and file_node.parm('mode').evalAsString() == 'out' and file_node.parm('rop').evalAsString() == node.path() and file_node.parm('overver').evalAsInt() == 0:
                file_node.parm('seqlabel').set(return_str)

        node.setColor(node_color)
        node.parm('seqlabel').set(return_str)

    def get_output_template(self, node):
        output_profile = self._get_output_profile(node)
        output_cache_template = self._app.get_template_by_name(output_profile["output_cache_template"])

        return output_cache_template


    ############################################################################
    # Private methods

    # remove underscores or minus in node and create camelcase name
    def _getNodeName(self, node):
        name = node.name()
        name = name.replace("-", " ").replace("_", " ")
        name = name.split()
        
        return name[0] + ''.join(i.capitalize() for i in name[1:])

    # compute the output path based on the current work file and backup template
    def _compute_backup_output_path(self, node):
        # get relevant fields from the current file path
        work_file_fields = self._get_hipfile_fields()

        if not work_file_fields:
            msg = "This Houdini file is not a Shotgun Toolkit work file!"
            raise sgtk.TankError(msg)

        # Get the type of output
        type_parm = node.parm('types')
        extension = type_parm.menuLabels()[type_parm.evalAsInt()]

        # create fields dict with all the metadata
        fields = {
            "name": work_file_fields.get("name", None),
            "node": self._getNodeName(node),
            "version": node.parm('ver').evalAsInt(),
            "ext": extension,
        }
        
        output_profile = self._get_output_profile(node)
        output_cache_template = self._app.get_template_by_name(
                        output_profile["output_backup_template"])

        fields.update(self._app.context.as_template_fields(
            output_cache_template))

        path = output_cache_template.apply_fields(fields)
        path = path.replace(os.path.sep, "/")

        return path

    # compute the output path based on the current work file and cache template
    def _compute_output_path(self, node):
        # get relevant fields from the current file path
        work_file_fields = self._get_hipfile_fields()

        if not work_file_fields:
            msg = "This Houdini file is not a Shotgun Toolkit work file!"
            raise sgtk.TankError(msg)

        # Get the type of output
        type_parm = node.parm('types')
        extension = type_parm.menuLabels()[type_parm.evalAsInt()]

        # create fields dict with all the metadata
        fields = {
            "name": work_file_fields.get("name", None),
            "node": self._getNodeName(node),
            "version": node.parm('ver').evalAsInt(),
            "ext": extension,
            "SEQ": "FORMAT: $F",
            "output_profile": self._get_output_profile(node),
            "hipfile": hou.hipFile.path()
        }

        # cache fields to accelerate path creation
        cachedFields = node.cachedUserData('fields')
        if cachedFields != fields:
            node.setCachedUserData('fields', fields.copy())
        else:
            return node.cachedUserData('pathCache')

        # get template
        output_cache_template = self._app.get_template_by_name(
                        fields["output_profile"]["output_cache_template"])

        fields.update(self._app.context.as_template_fields(
            output_cache_template))

        path = output_cache_template.apply_fields(fields)
        path = path.replace(os.path.sep, "/")

        node.setCachedUserData('pathCache', path)
        return path

    # get the current output profile
    def _get_output_profile(self, node=None):
        if not node:
            node = hou.pwd()

        output_profile_parm = node.parm(self.TK_OUTPUT_PROFILE_PARM)
        output_profile_name = \
            output_profile_parm.menuLabels()[output_profile_parm.eval()]
        output_profile = self._output_profiles[output_profile_name]

        return output_profile
            
    # extract fields from current Houdini file using the workfile template
    def _get_hipfile_fields(self):
        work_file_path = ''
        if hou.isUIAvailable():
            work_file_path = hou.hipFile.path()
        # Exeption for when we are on the render farm and using the backup hip
        # TODO put this environment variable in info.yml, hardcoded here
        else:
            env_hip = os.getenv('NOZ_HIPFILE')
            if env_hip:
                work_file_path = env_hip
            else:
                self._app.log_error('Could not find origin hip file!')

        work_fields = {}
        work_file_template = self._app.get_template("work_file_template")
        if (work_file_template and 
            work_file_template.validate(work_file_path)):
            work_fields = work_file_template.get_fields(work_file_path)

        return work_fields

    # get the render path from current item in the output path parm menu
    def _get_render_path(self, node):
        output_parm = node.parm(self.NODE_OUTPUT_PATH_PARM)
        path = output_parm.menuLabels()[output_parm.eval()]
        return path

    # returns the files on disk associated with this node
    def _get_rendered_files(self, node):
        file_name = self._get_render_path(node)

        output_profile = self._get_output_profile(node)

        # get the output cache template for the current profile
        output_cache_template = self._app.get_template_by_name(
            output_profile["output_cache_template"])

        if not output_cache_template.validate(file_name):
            msg = ("Unable to validate files on disk for node %s."
                   "The path '%s' is not recognized by Shotgun."
                   % (node.name(), file_name))
            self._app.log_error(msg)
            return []
            
        fields = output_cache_template.get_fields(file_name)

        # get the actual file paths based on the template. Ignore any sequence
        # or eye fields
        return self._app.tank.paths_from_template(
            output_cache_template, fields, ["SEQ", "eye"])

################################################################################
# Utility methods

# Copy all the input connections from this node to the target node.
def _copy_inputs(source_node, target_node):
    input_connections = source_node.inputConnections()
    num_target_inputs = len(target_node.inputConnectors())

    if len(input_connections) > num_target_inputs:
        raise hou.InvalidInput(
            "Not enough inputs on target node. Cannot copy inputs from "
            "'%s' to '%s'" % (source_node, target_node)
        )
        
    for connection in input_connections:
        target_node.setInput(connection.inputIndex(),
            connection.inputNode())

# Copy parameter values of the source node to those of the target node if a
# parameter with the same name exists.
def _copy_parm_values(source_node, target_node, excludes=None):
    if not excludes:
        excludes = []

    # build a parameter list from the source node, ignoring the excludes
    source_parms = [
        parm for parm in source_node.parms() if parm.name() not in excludes]

    for source_parm in source_parms:

        source_parm_template = source_parm.parmTemplate()

        # skip folder parms
        if isinstance(source_parm_template, hou.FolderSetParmTemplate):
            continue

        target_parm = target_node.parm(source_parm.name())

        # if the parm on the target node doesn't exist, skip it
        if target_parm is None:
            continue

        # if we have keys/expressions we need to copy them all.
        if source_parm.keyframes():
            for key in source_parm.keyframes():
                target_parm.setKeyframe(key)
        else:
            # if the parameter is a string, copy the raw string.
            if isinstance(source_parm_template, hou.StringParmTemplate):
                target_parm.set(source_parm.unexpandedString())
            # copy the evaluated value
            else:
                try:
                    target_parm.set(source_parm.eval())
                except TypeError:
                    # The pre- and post-script type comboboxes changed sometime around
                    # 16.5.439 to being string type parms that take the name of the language
                    # (hscript or python) instead of an integer index of the combobox item
                    # that's selected. To support both, we try the old way (which is how our
                    # otl is setup to work), and if that fails we then fall back on mapping
                    # the integer index from our otl's parm over to the string language name
                    # that the geometry node is expecting.
                    if source_parm.name().startswith("lpre") or source_parm.name().startswith("lpost"):
                        value_map = ["hscript", "python"]
                        target_parm.set(value_map[source_parm.eval()])
                    else:
                        raise

# return the menu label for the supplied parameter
def _get_output_menu_label(parm):
    if parm.menuItems()[parm.eval()] == "sgtk":
        # evaluated sgtk path from item
        return parm.menuLabels()[parm.eval()] 
    else:
        # output path from menu label
        return parm.menuItems()[parm.eval()] 

# move all the output connections from the source node to the target node
def _move_outputs(source_node, target_node):
    for connection in source_node.outputConnections():
        output_node = connection.outputNode()
        output_node.setInput(connection.inputIndex(), target_node)

# saves output connections into user data of target node. Needed when target
# node doesn't have outputs.
def _save_outputs_to_user_data(source_node, target_node):
    output_connections = source_node.outputConnections()
    if not output_connections:
        return

    outputs = []
    for connection in output_connections:
        output_dict = {
            'node': connection.outputNode().path(),
            'input': connection.inputIndex(),
        }
        outputs.append(output_dict)

    # get the current encoder for the handler
    handler_cls = TkGeometryNodeHandler
    codecs = handler_cls.TK_OUTPUT_CONNECTION_CODECS
    encoder = codecs[handler_cls.TK_OUTPUT_CONNECTION_CODEC]['encode']

    # encode and prepend the current codec name
    data_str = handler_cls.TK_OUTPUT_CONNECTION_CODEC + ":" + encoder(outputs)

    # set the encoded data string on the input node
    target_node.setUserData(handler_cls.TK_OUTPUT_CONNECTIONS_KEY, data_str)

# restore output connections from this node to the target node.
def _restore_outputs_from_user_data(source_node, target_node):
    data_str = source_node.userData(
        TkGeometryNodeHandler.TK_OUTPUT_CONNECTIONS_KEY)

    if not data_str:
        return

    # parse the data str to determine the codec used
    sep_index = data_str.find(":")
    codec_name = data_str[:sep_index]
    data_str = data_str[sep_index + 1:]

    # get the matching decoder based on the codec name
    handler_cls = TkGeometryNodeHandler
    codecs = handler_cls.TK_OUTPUT_CONNECTION_CODECS
    decoder = codecs[codec_name]['decode']

    # decode the data str back into original python objects
    outputs = decoder(data_str)

    if not outputs:
        return

    for connection in outputs:
        output_node = hou.node(connection['node'])
        output_node.setInput(connection['input'], target_node)