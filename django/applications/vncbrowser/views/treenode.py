import json

from django.http import HttpResponse
from vncbrowser.models import ClassInstance, TreenodeClassInstance, Treenode, \
        Double3D, ClassInstanceClassInstance
from vncbrowser.transaction import transaction_reportable_commit_on_success
from vncbrowser.views import catmaid_can_edit_project
from vncbrowser.catmaid_replacements import get_relation_to_id_map, get_class_to_id_map
from common import insert_into_log


@catmaid_can_edit_project
@transaction_reportable_commit_on_success
def create_treenode(request, project_id=None, logged_in_user=None):
    """
    Add a new treenode to the database
    ----------------------------------

    1. Add new treenode for a given skeleton id. Parent should not be empty.
    return: new treenode id

    2. Add new treenode (root) and create a new skeleton (maybe for a given neuron)
    return: new treenode id and skeleton id.

    If a neuron id is given, use that one to create the skeleton as a model of it.
    """

    def insert_new_treenode(parent_id=None, skeleton=None):
        new_treenode = Treenode()
        new_treenode.user = logged_in_user
        new_treenode.project_id = project_id
        new_treenode.location = Double3D(float(params['x']), float(params['y']), float(params['z']))
        new_treenode.radius = params['radius']
        new_treenode.skeleton = skeleton
        new_treenode.confidence = int(params['confidence'])
        if parent_id:
            new_treenode.parent_id = parent_id
        new_treenode.save()
        return new_treenode

    def make_treenode_element_of_skeleton(treenode, skeleton):
        new_treenode_ci = TreenodeClassInstance()
        new_treenode_ci.user = logged_in_user
        new_treenode_ci.project_id = project_id
        new_treenode_ci.relation_id = relation_map['element_of']
        new_treenode_ci.treenode = treenode
        new_treenode_ci.class_instance = skeleton
        new_treenode_ci.save()

    def create_relation(relation_id, instance_a_id, instance_b_id):
        neuron_relation = ClassInstanceClassInstance()
        neuron_relation.user = logged_in_user
        neuron_relation.project_id = project_id
        neuron_relation.relation_id = relation_id
        neuron_relation.class_instance_a_id = instance_a_id
        neuron_relation.class_instance_b_id = instance_b_id
        neuron_relation.save()
        return neuron_relation

    def relate_neuron_to_skeleton(neuron, skeleton):
        return create_relation(relation_map['model_of'], skeleton.id, neuron.id)

    params = {}
    default_values = {
            'x': 0,
            'y': 0,
            'z': 0,
            'confidence': 0,
            'useneuron': -1,
            'parent_id': 0,
            'radius': 0,
            'targetgroup': 'none',
            'confidence': 0
            }
    for p in default_values.keys():
        params[p] = request.POST.get(p, default_values[p])

    relation_map = get_relation_to_id_map(project_id)
    class_map = get_class_to_id_map(project_id)

    if params['parent_id'] != -1:  # A root node and parent node exist
        try:
            # Retrieve skeleton of parent
            p_skeleton = TreenodeClassInstance.objects.filter(
                    treenode=['parent_id'],
                    relation=relation_map['element_of'],
                    project=project_id)[0].class_instance
        except IndexError:
            return HttpResponse(json.dumps({'error': 'Can not find skeleton for parent treenode %s in this project.' % ['parent_id']}))

        try:
            new_treenode = insert_new_treenode(params['parent_id'], p_skeleton)
        except:
            return HttpResponse(json.dumps({'error': 'Could not insert new treenode!'}))
        try:
            make_treenode_element_of_skeleton(new_treenode, p_skeleton)
        except:
            return HttpResponse(json.dumps({'error': 'Could not create element_of relation between treenode and skeleton!'}))

        return HttpResponse(json.dumps({'treenode_id': new_treenode.id, 'skeleton_id': p_skeleton.id}))

    else:
        # No parent node: We must create a new root node, which needs a
        # skeleton and a neuron to belong to.
        try:
            new_skeleton = ClassInstance()
            new_skeleton.user = logged_in_user
            new_skeleton.project_id = project_id
            new_skeleton.class_id = class_map['skeleton']
            new_skeleton.name = 'skeleton'
            new_skeleton.save()
            new_skeleton.name = 'skeleton %d' % new_skeleton.id
            new_skeleton.save()
        except:
            return HttpResponse(json.dumps({'error': 'Could not insert new treenode instance!'}))

        if params['useneuron'] != -1:  # A neuron already exists, so we use it
            try:
                relate_neuron_to_skeleton(params['useneuron'], new_skeleton)
            except:
                return HttpResponse(json.dumps({'error': 'Could not relate the neuron model to the new skeleton!'}))

            try:
                new_treenode = insert_new_treenode(None, new_skeleton)
            except:
                return HttpResponse(json.dumps({'error': 'Could not insert new treenode!'}))
            try:
                make_treenode_element_of_skeleton(new_treenode, new_skeleton)
            except:
                return HttpResponse(json.dumps({'error': 'Could not create element_of relation between treenode and skeleton!'}))

            return HttpResponse(json.dumps({
                'treenode_id': new_treenode.id,
                'skeleton_id': new_skeleton.id,
                'neuron_id': params['useneuron']}))
        else:
            # A neuron does not exist, therefore we put the new skeleton
            # into a new neuron, and put the new neuron into the fragments group.
            try:
                new_neuron = ClassInstance()
                new_neuron.user = logged_in_user
                new_neuron.project_id = project_id
                new_neuron.class_id = class_map['neuron']
                new_neuron.name = 'neuron'
                new_neuron.save()
                new_neuron.name = 'neuron %d' % new_neuron.id
                new_neuron.save()
            except:
                return HttpResponse(json.dumps({'error': 'Failed to insert new instance of a neuron.'}))

            try:
                relate_neuron_to_skeleton(new_neuron, new_skeleton)
            except:
                return HttpResponse(json.dumps({'error': 'Could not relate the neuron model to the new skeleton!'}))

            # Add neuron to fragments
            try:
                fragment_group = ClassInstance.filter(
                        name=params['targetgroup'],
                        project=project_id)[0]
            except IndexError:
                # If the fragments group does not exist yet, must create it and add it:
                try:
                    fragment_group = ClassInstance()
                    fragment_group.user = logged_in_user
                    fragment_group.project = project_id
                    fragment_group.class_column = class_map['group']
                    fragment_group.name = params['targetgroup']
                    fragment_group.save()
                except:
                    return HttpResponse(json.dumps({'error': 'Failed to insert new instance of group.'}))

                try:
                    root = ClassInstance.objects.filter(
                            project=project_id,
                            class_column=class_map['root'])[0]
                except IndexError:
                    return HttpResponse(json.dumps({'error': 'Failed to retrieve root.'}))

                try:
                    create_relation(relation_map['part_of'], fragment_group.id, root.id)
                except:
                    return HttpResponse(json.dumps({'error': 'Failed to insert part_of relation between root node and fragments group.'}))

            try:
                create_relation(relation_map['part_of'], new_neuron.id, fragment_group.id)
            except:
                return HttpResponse(json.dumps({'error': 'Failed to insert part_of relation between neuron id and fragments group.'}))

            try:
                insert_new_treenode(None, new_skeleton)
            except:
                return HttpResponse(json.dumps({'error': 'Failed to insert instance of treenode.'}))

            insert_into_log(project_id, logged_in_user.id, 'create_neuron', new_treenode.location, 'Create neuron %d and skeleton %d' % new_neuron.id, new_skeleton.id)

            return HttpResponse(json.dumps({
                'skeleton_id': new_skeleton.id,
                'neuron_id': new_neuron.id,
                'fragmentgroup_id': fragment_group.id
                }))
