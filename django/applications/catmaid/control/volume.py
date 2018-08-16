# -*- coding: utf-8 -*-

import json
import re

from catmaid.control.authentication import requires_user_role, user_can_edit
from catmaid.models import UserRole, Project, Volume
from catmaid.serializers import VolumeSerializer

from django.db import connection
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from rest_framework.decorators import api_view
from rest_framework.response import Response

from six.moves import map
from six import string_types


num = '[-+]?[0-9]*.?[0-9]+'
bbox_re = r'BOX3D\(({0})\s+({0})\s+({0}),\s*({0})\s+({0})\s+({0})\)'.format(num)

def get_req_coordinate(request_dict, c):
    """Get a coordinate from a request dictionary or error.
    """
    v = request_dict.get(c, None)
    if not v:
        raise ValueError("Coordinate parameter %s missing." % c)
    return float(v)

def require_option(obj, field):
    """Raise an exception if a field is missing
    """
    if field in obj:
        return obj.get(field)
    else:
        raise ValueError("Parameter '{}' is missing".format(field))

def get_volume_instance(project_id, user_id, options):
    vtype = options.get("type", None)
    validate_vtype(vtype)

    init = volume_type.get(vtype)
    return init(project_id, user_id, options)

class PostGISVolume(object):
    """Volumes are supposed to create Volume model compatible data in the volume
    table by using PostGIS volumes.
    """

    def __init__(self, project_id, user_id, options):
        self.id = options.get('id', None)
        self.project_id = project_id
        self.user_id = user_id
        self.title = options.get('title') if self.id else require_option(options, "title")
        self.comment = options.get("comment", None)

    def get_geometry(self):
        return None

    def get_params(self):
        return None

    def save(self):
        surface = self.get_geometry()
        cursor = connection.cursor()
        extra_params = self.get_params() or {}
        if self.id:
            params = {
                "id": self.id,
                "project_id": self.project_id or 'project_id',
            }
            editable_params = {
                "editor_id": self.user_id,
                "name": self.title,
                "comment": self.comment,
                'geometry': surface
            }
            params.update(editable_params)
            params.update(extra_params)
            fields = [k for k in editable_params.keys() if editable_params.get(k)]
            # If surface is none, the old value will be used. This makes it
            # possible to update the volume without overriding its geometry.
            cursor.execute("""
                UPDATE catmaid_volume SET ({fields}) = ({templates})
                WHERE id=%(id)s
                RETURNING id
            """.format(**{
                'fields': ', '.join(fields + ['edition_time']),
                'templates': ', '.join(['%({})s'.format(f) for f in fields] + ['now()'])
            }), params)
        else:
            params = {
                "uid": self.user_id,
                "pid": self.project_id,
                "t": self.title,
                "c": self.comment,
            }
            params.update(extra_params)

            if not surface:
                raise ValueError("Can't create new volume without mesh")

            cursor.execute("""
                INSERT INTO catmaid_volume (user_id, project_id, editor_id, name,
                        comment, creation_time, edition_time, geometry)
                VALUES (%(uid)s, %(pid)s, %(uid)s, %(t)s, %(c)s, now(), now(), """ +
                           surface + """)
                RETURNING id;""", params)

        return cursor.fetchone()[0]

class TriangleMeshVolume(PostGISVolume):
    """A generic triangle mesh, provided from an external source.
    """
    def __init__(self, project_id, user_id, options):
        super(TriangleMeshVolume, self).__init__(project_id, user_id, options)
        input_mesh = options.get("mesh", None)
        if input_mesh:
            mesh_type = type(input_mesh)
            if list == mesh_type:
                self.mesh = input_mesh
            elif mesh_type in string_types:
                self.mesh = json.loads(input_mesh)
            else:
                raise ValueError("Unknown mesh type: " + str(mesh_type))
        else:
            self.mesh = None

    def get_params(self):
        return None

    def get_geometry(self):
        return TriangleMeshVolume.fromLists(self.mesh) if self.mesh else None

    @classmethod
    def fromLists(cls, mesh):
        """Expect mesh to be a list of two lists: [[points], [triangles]]. The
        list of points contains lists of three numbers, each one representing a
        vertex in the mesh. The array of triangles also contains three element
        lists as items. Each one represents a triangle based on the points in
        the other array, that are referenced by the triangle index values.
        """
        def pg_point(p):
            return '{} {} {}'.format(p[0], p[1], p[2])

        def pg_face(points, f):
            p0 = pg_point(points[f[0]])
            return '(({}, {}, {}, {}))'.format(p0, pg_point(points[f[1]]),
                 pg_point(points[f[2]]), p0)

        points, faces = mesh
        triangles = [pg_face(points, f) for f in faces]
        return "ST_GeomFromEWKT('TIN (%s)')" % ','.join(triangles)

class BoxVolume(PostGISVolume):

    def __init__(self, project_id, user_id, options):
        super(BoxVolume, self).__init__(project_id, user_id, options)
        self.min_x = get_req_coordinate(options, "min_x")
        self.min_y = get_req_coordinate(options, "min_y")
        self.min_z = get_req_coordinate(options, "min_z")
        self.max_x = get_req_coordinate(options, "max_x")
        self.max_y = get_req_coordinate(options, "max_y")
        self.max_z = get_req_coordinate(options, "max_z")

    def get_geometry(self):
        return """ST_GeomFromEWKT('POLYHEDRALSURFACE (
            ((%(lx)s %(ly)s %(lz)s, %(lx)s %(hy)s %(lz)s, %(hx)s %(hy)s %(lz)s,
              %(hx)s %(ly)s %(lz)s, %(lx)s %(ly)s %(lz)s)),
            ((%(lx)s %(ly)s %(lz)s, %(lx)s %(hy)s %(lz)s, %(lx)s %(hy)s %(hz)s,
              %(lx)s %(ly)s %(hz)s, %(lx)s %(ly)s %(lz)s)),
            ((%(lx)s %(ly)s %(lz)s, %(hx)s %(ly)s %(lz)s, %(hx)s %(ly)s %(hz)s,
              %(lx)s %(ly)s %(hz)s, %(lx)s %(ly)s %(lz)s)),
            ((%(hx)s %(hy)s %(hz)s, %(hx)s %(ly)s %(hz)s, %(lx)s %(ly)s %(hz)s,
              %(lx)s %(hy)s %(hz)s, %(hx)s %(hy)s %(hz)s)),
            ((%(hx)s %(hy)s %(hz)s, %(hx)s %(ly)s %(hz)s, %(hx)s %(ly)s %(lz)s,
              %(hx)s %(hy)s %(lz)s, %(hx)s %(hy)s %(hz)s)),
            ((%(hx)s %(hy)s %(hz)s, %(hx)s %(hy)s %(lz)s, %(lx)s %(hy)s %(lz)s,
              %(lx)s %(hy)s %(hz)s, %(hx)s %(hy)s %(hz)s)))')"""

    def get_params(self):
        return {
            "lx": self.min_x,
            "ly": self.min_y,
            "lz": self.min_z,
            "hx": self.max_x,
            "hy": self.max_y,
            "hz": self.max_z,
            "id": self.id
        }


volume_type = {
    "box": BoxVolume,
    "trimesh": TriangleMeshVolume
}

def validate_vtype(vtype):
    """Validate the given type or error.
    """
    if not vtype:
        raise ValueError("Type parameter missing. It should have one of the "
                "following options: " + ", ".join(volume_type.keys()))
    if vtype not in volume_type.keys():
        raise ValueError("Type has to be one of the following: " +
                volume_type.keys().join(", "))
    return vtype

@api_view(['GET'])
@requires_user_role([UserRole.Browse])
def volume_collection(request, project_id):
    """Get a collection of all available volumes.
    """
    if request.method == 'GET':
        p = get_object_or_404(Project, pk=project_id)
        # FIXME: Parsing our PostGIS geometry with GeoDjango doesn't work
        # anymore since Django 1.8. Therefore, the geometry fields isn't read.
        # See: https://github.com/catmaid/CATMAID/issues/1250
        fields = ('id', 'name', 'comment', 'user', 'editor', 'project',
                'creation_time', 'edition_time')
        volumes = Volume.objects.filter(project_id=project_id).values(*fields)
        return Response(volumes)

def get_volume_details(project_id, volume_id):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT id, project_id, name, comment, user_id, editor_id,
            creation_time, edition_time, Box3D(geometry), ST_Asx3D(geometry)
        FROM catmaid_volume v
        WHERE id=%s and project_id=%s""",
        (volume_id, project_id))
    volume = cursor.fetchone()

    if not volume:
        raise ValueError("Could not find volume " + volume_id)

    # Parse bounding box into dictionary, coming in format "BOX3D(0 0 0,1 1 1)"
    bbox_matches = re.search(bbox_re, volume[8])
    if not bbox_matches or len(bbox_matches.groups()) != 6:
        raise ValueError("Couldn't create bounding box for geometry")
    bbox = list(map(float, bbox_matches.groups()))

    return {
        'id': volume[0],
        'project_id': volume[1],
        'name': volume[2],
        'comment': volume[3],
        'user_id': volume[4],
        'editor_id': volume[5],
        'creation_time': volume[6],
        'edition_time': volume[7],
        'bbox': {
            'min': {'x': bbox[0], 'y': bbox[1], 'z': bbox[2]},
            'max': {'x': bbox[3], 'y': bbox[4], 'z': bbox[5]}
        },
        'mesh': volume[9]
    }


@api_view(['GET', 'POST', 'DELETE'])
@requires_user_role([UserRole.Browse])
def volume_detail(request, project_id, volume_id):
    """Get detailed information on a spatial volume or set its properties..

    The result will contain the bounding box of the volume's geometry and the
    actual geometry encoded in X3D format. The response might might therefore be
    relatively large.
    """
    p = get_object_or_404(Project, pk=project_id)
    if request.method == 'GET':
        volume = get_volume_details(p.id, volume_id)
        return Response(volume)
    elif request.method == 'POST':
        return update_volume(request, project_id=project_id, volume_id=volume_id)
    elif request.method == 'DELETE':
        return remove_volume(request, project_id=project_id, volume_id=volume_id)

@requires_user_role([UserRole.Annotate])
def remove_volume(request, project_id, volume_id):
    """Remove a particular volume, if the user has permission to it.
    """
    cursor = connection.cursor()
    cursor.execute("""
        SELECT user_id FROM catmaid_volume WHERE id=%s
    """, (volume_id,))
    rows = cursor.fetchall()
    if 0 == len(rows):
        raise ValueError("Could not find volume with ID {}".format(volume_id))
    volume_user_id = rows[0][0]

    if not user_can_edit(connection.cursor(), request.user.id, volume_user_id) and not request.user.is_superuser:
        raise Exception("You don't have permissions to delete this volume")

    cursor.execute("""
        DELETE FROM catmaid_volume WHERE id=%s
    """, (volume_id,))

    return Response({
        "success": True,
        "volume_id": volume_id
    })

@requires_user_role([UserRole.Annotate])
def update_volume(request, project_id, volume_id):
    """Update properties of an existing volume

    Only the fields that are provided are updated. If no mesh or bounding box
    parameter is changed, no type has to be provided.
    ---
    parameters:
      - name: type
        description: Type of volume to edit
        paramType: form
        type: string
        enum: ["box", "trimesh"]
        required: false
      - name: title
        description: Title of volume
        type: string
        required: false
      - name: comment
        description: A comment on a volume
        type: string
        required: false
    type:
      'success':
        type: boolean
        required: true
      'volume_id':
        type: integer
        required: true
    """
    if request.method != "POST":
        raise ValueError("Volume updates require a POST request")

    options = {
        "id": volume_id,
        "type": request.POST.get('type'),
        "title": request.POST.get('title'),
        "comment": request.POST.get('comment')
    }
    try:
        instance = get_volume_instance(project_id, request.user.id, options)
    except ValueError as e:
        if volume_id:
            instance = PostGISVolume(project_id, request.user.id, options)
        else:
            raise e
    volume_id = instance.save()

    return Response({
        "success": True,
        "volume_id": volume_id
    })

@api_view(['POST'])
@requires_user_role([UserRole.Annotate])
def add_volume(request, project_id):
    """Create a new volume

    The ID of the newly created volume is returned. Currently, box volumes and
    triangle meshes are supported. Which one is created depends on the "type"
    parameter, which can be either set to "box" or to "trimesh".

    If a triangle mesh should be created, the "mesh" parameter is expected to
    hold the complete volume. It is expected to be a string that encodes two
    lists in JSON format: [[points], [triangles]]. The list of points contains
    lists of three numbers, each one representing a vertex in the mesh. The
    array of triangles also contains three element lists as items. Each one
    represents a triangle based on the points in the other array, that are
    referenced by the triangle index values.
    ---
    parameters:
      - name: type
        description: Type of volume to create
        paramType: form
        type: string
        enum: ["box", "trimesh"]
        required: true
      - name: title
        description: Title of volume
        type: string
        required: true
      - name: comment
        description: An optional comment
        type: string
        required: false
      - name: mesh
        description: Triangle mesh
        paramType: form
        type: string
        required: false
      - name: minx
        description: Minimum x coordinate of box
        paramType: form
        type: integer
        required: false
      - name: miny
        description: Minimum y coordinate of box
        paramType: form
        type: integer
        required: false
      - name: minz
        description: Minimum z coordinate of box
        paramType: form
        type: integer
        required: false
      - name: maxx
        description: Maximum x coordinate of box
        paramType: form
        type: integer
        required: false
      - name: maxy
        description: Maximum y coordinate of box
        paramType: form
        type: integer
        required: false
      - name: maxz
        description: Maximum z coordinate of box
        paramType: form
        type: integer
        required: false
    type:
      'success':
        type: boolean
        required: true
      'volume_id':
        type: integer
        required: true
    """
    # Use DRF's request.data to be able to also be able to parse
    # application/json content type requests. This can be convenient when
    # importing meshes.
    instance = get_volume_instance(project_id, request.user.id, request.data)
    volume_id = instance.save()

    return Response({
        "success": True,
        "volume_id": volume_id
    })

@api_view(['GET'])
@requires_user_role([UserRole.Browse])
def intersects(request, project_id, volume_id):
    """Test if a point intersects with the bounding box of a given volume.
    ---
    parameters:
      - name: x
        description: X coordinate of point to test
        paramType: query
        type: number
      - name: y
        description: Y coordinate of point to test
        paramType: query
        type: number
      - name: z
        description: Z coordinate of point to test
        paramType: query
        type: number
    type:
      'intersects':
        type: boolean
        required: true
    """
    if request.method != 'GET':
        return

    p = get_object_or_404(Project, pk=project_id)
    x = request.GET.get('x', None)
    y = request.GET.get('y', None)
    z = request.GET.get('z', None)
    if None in (x,y,z):
        raise ValueError("Please provide valid X, Y and Z coordinates")

    x, y, z = float(x), float(y), float(z)

    # This test works only for boxes, because it only checks bounding box
    # overlap (&&& operator).
    cursor = connection.cursor()
    cursor.execute("""
        SELECT pt.geometry &&& catmaid_volume.geometry
        FROM (SELECT 'POINT(%s %s %s)'::geometry) AS pt, catmaid_volume
        WHERE catmaid_volume.id=%s""",
        (x, y, z, volume_id))

    result = cursor.fetchone()

    return JsonResponse({
        'intersects': result[0]
    })

def getPrimaryVolumes(project_id):
    '''
        Helper function that returns list of all volumes considered as primary neuropils 
        by using the standardized volume naming schema to filter out the others - modified version of get_volume_details

    '''
    params = {
        'project_id': project_id
    }

    query = '''
    SELECT id, project_id, name, comment, user_id, editor_id,
                 creation_time, edition_time, Box3D(geometry), ST_Asx3D(geometry)
             FROM catmaid_volume v
             WHERE v.project_id= %(project_id)s AND 
                  (name LIKE '%%_R' OR name LIKE '%%_L' OR char_length(name)<5) AND char_length(name) <= 10 AND 
                   name NOT LIKE 'v14%%'
    '''

    cursor = connection.cursor()
    cursor.execute(query, params)
    volume = cursor.fetchall()

    return volume

def makeVolumeBB(project_id):
    '''
        Helper function - Directly copied from within the get_volume_details functions - just wrapped it in a for loop so that it
        would include information on all relevant neuropils 
    '''
    myTupList = []
    v = getPrimaryVolumes(project_id)
    for volume in v:

    # Parse bounding box into dictionary, coming in format "BOX3D(0 0 0,1 1 1)"
        bbox_matches = re.search(bbox_re, volume[8])
        if not bbox_matches or len(bbox_matches.groups()) != 6:
            raise ValueError("Couldn't create bounding box for geometry")
        bbox = list(map(float, bbox_matches.groups()))
        myTuple = {
            'id': volume[0],
            'project_id': volume[1],
            'name': volume[2],
            'comment': volume[3],
            'user_id': volume[4],
            'editor_id': volume[5],
            'creation_time': volume[6],
            'edition_time': volume[7],
            'bbox': {
                'min': {'x': bbox[0], 'y': bbox[1], 'z': bbox[2]},
                'max': {'x': bbox[3], 'y': bbox[4], 'z': bbox[5]}
            },
            'mesh': volume[9]
        }
        myTupList.append(myTuple)
    return myTupList


def getBBintersections(project_id):
    '''
    helper function that returns paramSet - a dictionary of dictionaries as: 
    {'volume name' : {'project_id':int,'minx':float, 'miny':float, 'minz':float, 'maxx':float, 'maxy':float, 
     'maxz':float, 'halfzdiff':float, 'min_nodes': int, 'min_cable':int}}

    '''
    volumeSet = makeVolumeBB(project_id)
    paramSet = {}
    for volume in volumeSet:
        params = {
            'project_id': project_id
        }
        bbmin, bbmax = volume['bbox']['min'], volume['bbox']['max']
        params['minx'] = bbmin['x']
        params['miny'] = bbmin['y']
        params['minz'] = bbmin['z']
        params['maxx'] = bbmax['x']
        params['maxy'] = bbmax['y']
        params['maxz'] = bbmax['z']

        params['halfzdiff'] = abs(params['maxz'] - params['minz']) * 0.5
        params['halfz'] = params['minz'] + (params['maxz'] - params['minz']) * 0.5
        params['min_nodes'] = 1 #int(data.get('min_nodes', 0))
        params['min_cable'] = 1 #int(data.get('min_cable', 0))
       #params['skeleton_ids'] = get_request_list(data, 'skeleton_ids', map_fn=int)
        paramSet[volume['name']] = params

    return paramSet



@api_view(['GET', 'POST'])
@requires_user_role(UserRole.Browse)
def skeletonInnervations(skeleton_ids, project_id):
    '''
        Test environment only contains two skeletons - based on that, sql query always returns list of all 
        SKIDs but all data (about both skeletons) is contained in the first SKID in the list - if this changes,
        write an else statement for: len(cleanResults) >1.
        ---
        parameters:
            - name: skeleton_ids
              required: True
              type: array [int]
              paramType: Form
            - name: paramSet
              required: True
              type: dict
              paramType: functionCall
    '''
    

    paramSet = getBBintersections(skeleton_ids)
    
    skelVols = {}
    myResults = {}
    for i in skeleton_ids:
        myResults[str(i)] = {}
        skelVols[str(i)] = []

    for params in paramSet:
        extra_where = []
        extra_joins = []


        paramSet[params]['skeleton_ids'] = skeleton_ids
        needs_summary = paramSet[params]['min_nodes'] > 0 or paramSet[params]['min_cable'] > 0

        #extra_joins.append(skeletonIDs)
        if paramSet[params]['min_nodes'] > 1:
            extra_where.append("""
                css.num_nodes >= %(min_nodes)s
            """)
        if needs_summary:
            extra_joins.append("""
                JOIN catmaid_skeleton_summary css
                    ON css.skeleton_id = skeleton.id
            """)
        if paramSet[params]['min_cable'] > 0:
            extra_where.append("""
                css.cable_length >= %(min_cable)s
            """)
        if skeleton_ids:
            extra_joins.append("""
                        JOIN UNNEST(%(skeleton_ids)s::int[]) query_skeleton(id)
                            ON query_skeleton.id = skeleton.id
                    """)
        node_query = """
                    SELECT DISTINCT t.skeleton_id
                    FROM (
                      SELECT te.id, te.edge
                        FROM treenode_edge te
                        WHERE floatrange(ST_ZMin(te.edge),
                             ST_ZMax(te.edge), '[]') && floatrange(%(minz)s, %(maxz)s, '[)')
                          AND te.project_id = %(project_id)s
                      ) e
                      JOIN treenode t
                        ON t.id = e.id
                      WHERE e.edge && ST_MakeEnvelope(%(minx)s, %(miny)s, %(maxx)s, %(maxy)s)
                        AND ST_3DDWithin(e.edge, ST_MakePolygon(ST_MakeLine(ARRAY[
                            ST_MakePoint(%(minx)s, %(miny)s, %(halfz)s),
                            ST_MakePoint(%(maxx)s, %(miny)s, %(halfz)s),
                            ST_MakePoint(%(maxx)s, %(maxy)s, %(halfz)s),
                            ST_MakePoint(%(minx)s, %(maxy)s, %(halfz)s),
                            ST_MakePoint(%(minx)s, %(miny)s, %(halfz)s)]::geometry[])),
                            %(halfzdiff)s)
                """
        if extra_where:
            extra_where = 'WHERE ' + '\nAND '.join(extra_where)
        else:
            extra_where = ''
        query = """
            SELECT skeleton.id
            FROM (
                {node_query}
            ) skeleton(id)
            {extra_joins}
            {extra_where}
        """.format(**{
            'extra_joins': '\n'.join(extra_joins),
            'extra_where': extra_where,
            'node_query': node_query,
        })
        cursor = connection.cursor()
        cursor.execute(query, paramSet[params])
        for i in myResults:
            myResults[i][params] = cursor.fetchall()

    cleanedResults = {}
    for i in myResults:
        for item in myResults[i]:
            if len(myResults[i][item]) >= 1:
                cleanedResults[i] = myResults[i]
                break
    if(len(cleanedResults)) == 1:
        cleanedResults = cleanedResults[list(cleanedResults.keys())[0]]
        cleanResults = {}
        for bb in cleanedResults:
            if len(cleanedResults[bb]) >0:
                cleanResults[bb] = cleanedResults[bb]
                for tup in cleanResults[bb]:
                    skelVols[str(tup[0])].append(bb)

    #insert else statement here if data returned does not match test environment                
         
    return skelVols
