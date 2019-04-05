# Copyright 2012 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2012 Nebula, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from django.utils.translation import ugettext_lazy as _
from django.utils import translation
from django.utils.decorators import method_decorator

from django.views.decorators.debug import sensitive_post_parameters
from django.template.defaultfilters import floatformat
from django.conf import settings

from django.urls import reverse
from django.urls import reverse_lazy

from horizon import tables
from horizon import tabs
from horizon import messages
from horizon import forms
from horizon import views
from horizon import exceptions
from horizon.utils import csvbase
from horizon.utils import memoized
from horizon.utils import functions as utils

from openstack_dashboard import api
from openstack_dashboard import usage
from openstack_dashboard import policy
from openstack_dashboard.utils import futurist_utils
from openstack_dashboard.utils import identity

from openstack_dashboard.dashboards.main.overview \
    import tables as project_tables

from openstack_dashboard.dashboards.main.overview \
    import tables as user_tables

from openstack_dashboard.dashboards.main.overview \
    import tables as instance_tables

from openstack_dashboard.dashboards.main.overview \
    import tables as hypervisor_tables
import logging
LOG = logging.getLogger(__name__)

class IndexView(tables.MultiTableView):
    table_classes = (project_tables.TenantsTable,
                     instance_tables.AdminInstancesTable,
                     hypervisor_tables.AdminHypervisorsTable,
                     user_tables.UsersTable,)
    #tab_group_class = hypervisor_tabs.HypervisorHostTabs                 
    usage_class = usage.GlobalUsage
    template_name = 'main/overview/index.html'
    page_title = _("Main Page")
    roles=[]

    def needs_filter_first(self, table):
        return self._needs_filter_first

    def has_more_data(self, table):
        return self._more

    def get_tenants_data(self):
        for role in self.request.user.roles:
            self.roles.append(role.get('name'))

        if self.roles.__contains__("user"):
            self.template_name = 'main/overview/index_user.html'
        elif self.roles.__contains__('project_manager'):
            self.template_name = 'main/overview/index_pm.html'

        tenants = []
        marker = self.request.GET.get(
            project_tables.TenantsTable._meta.pagination_param, None)
        self._more = False

        if policy.check((("identity", "identity:list_projects"),),
                        self.request):

            domain_id = identity.get_domain_id_for_operation(self.request)
            try:
                if self.request.user.username == 'admin':
                    tenants, self._more = api.keystone.tenant_list(
                        self.request,
                        domain=domain_id,
                        paginate=True,
                        marker=marker)
                else:
                    tenants, self._more = api.keystone.tenant_my_list(
                        self.request,
                        user_id=self.request.user.id)
            except Exception:
                exceptions.handle(self.request,
                                  _("Unable to retrieve project list."))
        elif policy.check((("identity", "identity:list_user_projects"),),
                          self.request):
            try:
                tenants, self._more = api.keystone.tenant_list(
                    self.request,
                    user=self.request.user.id,
                    paginate=True,
                    marker=marker,
                    admin=False)
            except Exception:
                exceptions.handle(self.request,
                                  _("Unable to retrieve project information."))
        else:
            msg = \
                _("Insufficient privilege level to view project information.")
            messages.info(self.request, msg)

        if api.keystone.VERSIONS.active >= 3:
            domain_lookup = api.keystone.domain_lookup(self.request)
            for t in tenants:
                t.domain_name = domain_lookup.get(t.domain_id)
        
        return tenants

    
    # instance
    def _get_tenants(self):
        # Gather our tenants to correlate against IDs
        try:
            tenants, __ = api.keystone.tenant_list(self.request)
            return dict([(t.id, t) for t in tenants])
        except Exception:
            msg = _('Unable to retrieve instance project information.')
            exceptions.handle(self.request, msg)
            return {}

    def _get_images(self):
        # Gather our images to correlate againts IDs
        try:
            images, __, __ = api.glance.image_list_detailed(self.request)
            return dict([(image.id, image) for image in images])
        except Exception:
            msg = _("Unable to retrieve image list.")
            exceptions.handle(self.request, msg)
            return {}

    def _get_flavors(self):
        # Gather our flavors to correlate against IDs
        try:
            flavors = api.nova.flavor_list(self.request)
            return dict([(str(flavor.id), flavor) for flavor in flavors])
        except Exception:
            msg = _("Unable to retrieve flavor list.")
            exceptions.handle(self.request, msg)
            return {}

    def _get_instances(self, search_opts):
        try:
            instances, self._more = api.nova.server_list(
                self.request,
                search_opts=search_opts)
        except Exception:
            self._more = False
            instances = []
            exceptions.handle(self.request,
                              _('Unable to retrieve instance list.'))
        return instances

    def get_instances_data(self):
        instances = []

        if self.roles.__contains__('project_manager') or self.roles.__contains__('user'):
            marker = self.request.GET.get(project_tables.InstancesTable._meta.pagination_param, None)
            search_opts = {'marker': marker, 'paginate': True}

            image_dict, flavor_dict = futurist_utils.call_functions_parallel(
                self._get_images, self._get_flavors)  
            instances = self._get_instances(search_opts)

            # Loop through instances to get flavor info.
            for instance in instances:
                if hasattr(instance, 'image'):
                    # Instance from image returns dict
                    if isinstance(instance.image, dict):
                        image_id = instance.image.get('id')
                        if image_id in image_dict:
                            instance.image = image_dict[image_id]
                        # In case image not found in image_dict, set name to empty
                        # to avoid fallback API call to Glance in api/nova.py
                        # until the call is deprecated in api itself
                        else:
                            instance.image['name'] = _("-")

                flavor_id = instance.flavor["id"]
                if flavor_id in flavor_dict:
                    instance.full_flavor = flavor_dict[flavor_id]
                else:
                    # If the flavor_id is not in flavor_dict,
                    # put info in the log file.
                    LOG.info('Unable to retrieve flavor "%s" for instance "%s".',
                            flavor_id, instance.id)

            return instances
        else:
            marker = self.request.GET.get(
                instance_tables.AdminInstancesTable._meta.pagination_param, None)
            search_opts = {'marker': marker,
                            'paginate': True,
                            'all_tenants': True}

            results = futurist_utils.call_functions_parallel(
                self._get_images, self._get_flavors, self._get_tenants)
            image_dict, flavor_dict, tenant_dict = results

            instances = self._get_instances(search_opts)

            # Loop through instances to get image, flavor and tenant info.
            for inst in instances:
                if hasattr(inst, 'image') and isinstance(inst.image, dict):
                    image_id = inst.image.get('id')
                    if image_id in image_dict:
                        inst.image = image_dict[image_id]
                    # In case image not found in image_map, set name to empty
                    # to avoid fallback API call to Glance in api/nova.py
                    # until the call is deprecated in api itself
                    else:
                        inst.image['name'] = _("-")

                flavor_id = inst.flavor["id"]
                try:
                    if flavor_id in flavor_dict:
                        inst.full_flavor = flavor_dict[flavor_id]
                    else:
                        # If the flavor_id is not in flavor_dict list,
                        # gets it via nova api.
                        inst.full_flavor = api.nova.flavor_get(
                            self.request, flavor_id)
                except Exception:
                    msg = _('Unable to retrieve instance size information.')
                    exceptions.handle(self.request, msg)
                tenant = tenant_dict.get(inst.tenant_id, None)
                inst.tenant_name = getattr(tenant, "name", None)
            return instances


    # hypervisor resource    
    def get_hypervisors_data(self):
        hypervisors = []
        if self.roles.__contains__('user'):
            return hypervisors
        try:
            hypervisors = api.nova.hypervisor_list(self.request)
            hypervisors.sort(key=utils.natural_sort('hypervisor_hostname'))
        except Exception:
            exceptions.handle(self.request,
                            _('Unable to retrieve hypervisor information.'))
        return hypervisors

        
    # users
    def get_users_data(self):
        users = []
        self._needs_filter_first = False
        
        if policy.check((("identity", "identity:list_users"),),
                        self.request):

            domain_id = identity.get_domain_id_for_operation(self.request)
            try:
                if self.request.user.username == 'admin':
                    users = api.keystone.user_list(self.request,
                                                domain=domain_id)
                                                #filters=filters)
                else:
                    projects = api.keystone.tenant_list(self.request, 
                                                user=self.request.user.id,
                                                admin=True)
                    users = api.keystone.user_my_list(self.request,
                                                projects=projects)
            except Exception:
                exceptions.handle(self.request,
                                  _('Unable to retrieve user list.'))
        elif policy.check((("identity", "identity:get_user"),),
                          self.request):
            try:
                user = api.keystone.user_get(self.request,
                                             self.request.user.id,
                                             admin=False)
                users.append(user)
            except Exception:
                exceptions.handle(self.request,
                                  _('Unable to retrieve user information.'))
        else:
            msg = _("Insufficient privilege level to view user information.")
            messages.info(self.request, msg)

        if api.keystone.VERSIONS.active >= 3:
            domain_lookup = api.keystone.domain_lookup(self.request)
            for u in users:
                u.domain_name = domain_lookup.get(u.domain_id)
        return users