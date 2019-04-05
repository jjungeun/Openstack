# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from django.utils.translation import ungettext_lazy
from django.utils.translation import ugettext_lazy as _
from django.template.defaultfilters import floatformat
from django import urls
from django.urls import reverse
from django.utils.http import urlencode


from horizon.templatetags import sizeformat
from horizon.utils import filters
from horizon import tables
from horizon import forms

from keystoneclient import exceptions as keystone_exceptions

from django.template.defaultfilters import title
from django.template import defaultfilters

from openstack_dashboard.usage import quotas
from openstack_dashboard import api
from openstack_dashboard.dashboards.project.instances import audit_tables
from openstack_dashboard.dashboards.project.instances \
    import tables as project_tables
from openstack_dashboard import policy
from openstack_dashboard.views import get_url_with_pagination


################
### PROJECT  ###
################    

class RescopeTokenToProject(tables.LinkAction):
    name = "rescope"
    verbose_name = _("Set as Active Project")
    url = "switch_tenants"

    def allowed(self, request, project):
        # allow rescoping token to any project the user has a role on,
        # authorized_tenants, and that they are not currently scoped to
        return next((True for proj in request.user.authorized_tenants
                     if proj.id == project.id and
                     project.id != request.user.project_id and
                     project.enabled), False)

    def get_link_url(self, project):
        # redirects to the switch_tenants url which then will redirect
        # back to this page
        dash_url = reverse("horizon:identity:projects:index")
        base_url = reverse(self.url, args=[project.id])
        param = urlencode({"next": dash_url})
        return "?".join([base_url, param])


class UpdateMembersLink(tables.LinkAction):
    name = "users"
    verbose_name = _("Manage Members")
    url = "horizon:identity:projects:update"
    classes = ("ajax-modal",)
    icon = "pencil"
    policy_rules = (("identity", "identity:list_users"),
                    ("identity", "identity:list_roles"))

    def get_link_url(self, project):
        step = 'update_members'
        base_url = reverse(self.url, args=[project.id])
        param = urlencode({"step": step})
        return "?".join([base_url, param])

    def allowed(self, request, project):
        if api.keystone.is_multi_domain_enabled():
            # domain admin or cloud admin = True
            # project admin or member = False
            return api.keystone.is_domain_admin(request)
        else:
            return super(UpdateMembersLink, self).allowed(request, project)


class UpdateGroupsLink(tables.LinkAction):
    name = "groups"
    verbose_name = _("Modify Groups")
    url = "horizon:identity:projects:update"
    classes = ("ajax-modal",)
    icon = "pencil"
    policy_rules = (("identity", "identity:list_groups"),)

    def allowed(self, request, project):
        if api.keystone.is_multi_domain_enabled():
            # domain admin or cloud admin = True
            # project admin or member = False
            return api.keystone.is_domain_admin(request)
        else:
            return super(UpdateGroupsLink, self).allowed(request, project)

    def get_link_url(self, project):
        step = 'update_group_members'
        base_url = reverse(self.url, args=[project.id])
        param = urlencode({"step": step})
        return "?".join([base_url, param])


class UsageLink(tables.LinkAction):
    name = "usage"
    verbose_name = _("View Usage")
    url = "horizon:identity:projects:usage"
    icon = "stats"
    policy_rules = (("compute", "os_compute_api:os-simple-tenant-usage:show"),)

    def allowed(self, request, project):
        return (request.user.is_superuser and
                api.base.is_service_enabled(request, 'compute'))


class UpdateProject(policy.PolicyTargetMixin, tables.LinkAction):
    name = "update"
    verbose_name = _("Edit Project")
    url = "horizon:identity:projects:update"
    classes = ("ajax-modal",)
    icon = "pencil"
    policy_rules = (('identity', 'identity:update_project'),)
    policy_target_attrs = (("target.project.domain_id", "domain_id"),)

    def allowed(self, request, project):
        if api.keystone.is_multi_domain_enabled():
            # domain admin or cloud admin = True
            # project admin or member = False
            return api.keystone.is_domain_admin(request)
        else:
            return api.keystone.keystone_can_edit_project()

class ModifyQuotas(tables.LinkAction):
    name = "quotas"
    verbose_name = _("Modify Quotas")
    url = "horizon:identity:projects:update_quotas"
    classes = ("ajax-modal",)
    icon = "pencil"
    policy_rules = (('compute', "os_compute_api:os-quota-sets:update"),)

    def allowed(self, request, datum):
        if api.keystone.VERSIONS.active < 3:
            return True
        else:
            return (api.keystone.is_cloud_admin(request) and
                    quotas.enabled_quotas(request))

    def get_link_url(self, project):
        step = 'update_quotas'
        base_url = reverse(self.url, args=[project.id])
        param = urlencode({"step": step})
        return "?".join([base_url, param])


class DeleteTenantsAction(policy.PolicyTargetMixin, tables.DeleteAction):
    @staticmethod
    def action_present(count):
        return ungettext_lazy(
            u"Delete Project",
            u"Delete Projects",
            count
        )

    @staticmethod
    def action_past(count):
        return ungettext_lazy(
            u"Deleted Project",
            u"Deleted Projects",
            count
        )

    policy_rules = (("identity", "identity:delete_project"),)
    policy_target_attrs = ("target.project.domain_id", "domain_id"),

    def allowed(self, request, project):
        if api.keystone.is_multi_domain_enabled() \
                and not api.keystone.is_domain_admin(request):
            return False
        return api.keystone.keystone_can_edit_project()

    def delete(self, request, obj_id):
        api.keystone.tenant_delete(request, obj_id)

    def handle(self, table, request, obj_ids):
        response = \
            super(DeleteTenantsAction, self).handle(table, request, obj_ids)
        return response


class UpdateRow(tables.Row):
    ajax = True

    def get_data(self, request, project_id):
        project_info = api.keystone.tenant_get(request, project_id,
                                               admin=True)
        return project_info


class TenantsTable(tables.DataTable):
    name = tables.WrappingColumn('name', verbose_name=_('Name'),
                                 link=("horizon:identity:projects:detail"),
                                 form_field=forms.CharField(max_length=64))
    description = tables.Column(lambda obj: getattr(obj, 'description', None),
                                verbose_name=_('Description'),
                                form_field=forms.CharField(
                                    widget=forms.Textarea(attrs={'rows': 4}),
                                    required=False))
    # id = tables.Column('id', verbose_name=_('Project ID'))

    # if api.keystone.VERSIONS.active >= 3:
    #     domain_name = tables.Column(
    #         'domain_name', verbose_name=_('Domain Name'))

    enabled = tables.Column('enabled', verbose_name=_('Enabled'), status=True,
                            form_field=forms.BooleanField(
                                label=_('Enabled'),
                                required=False))

    def get_project_detail_link(self, project):
        # this method is an ugly monkey patch, needed because
        # the column link method does not provide access to the request
        if policy.check((("identity", "identity:get_project"),),
                        self.request, target={"project": project}):
            return reverse("horizon:identity:projects:detail",
                           args=(project.id,))
        return None

    def __init__(self, request, data=None, needs_form_wrapper=None, **kwargs):
        super(TenantsTable,
              self).__init__(request, data=data,
                             needs_form_wrapper=needs_form_wrapper,
                             **kwargs)
        # see the comment above about ugly monkey patches
        self.columns['name'].get_link_url = self.get_project_detail_link

    class Meta(object):
        name = "tenants"
        verbose_name = _("Classes")
        row_class = UpdateRow
        # row_actions = (UpdateMembersLink, UpdateGroupsLink, UpdateProject,
        #                UsageLink, ModifyQuotas, DeleteTenantsAction,
        #                RescopeTokenToProject)
        # # table_actions = (TenantFilterAction, CreateProject,
        #                 DeleteTenantsAction)
        pagination_param = "tenant_marker"

        
################
### INSTANCE ###
################

class AdminEditInstance(project_tables.EditInstance):
    url = "horizon:admin:instances:update"


class AdminConsoleLink(project_tables.ConsoleLink):
    url = "horizon:admin:instances:detail"


class AdminLogLink(project_tables.LogLink):
    url = "horizon:admin:instances:detail"


class MigrateInstance(policy.PolicyTargetMixin, tables.BatchAction):
    name = "migrate"
    classes = ("btn-migrate",)
    policy_rules = (("compute", "os_compute_api:os-migrate-server:migrate"),)
    help_text = _("Migrating instances may cause some unrecoverable results.")
    action_type = "danger"

    @staticmethod
    def action_present(count):
        return ungettext_lazy(
            u"Migrate Instance",
            u"Migrate Instances",
            count
        )

    @staticmethod
    def action_past(count):
        return ungettext_lazy(
            u"Scheduled migration (pending confirmation) of Instance",
            u"Scheduled migration (pending confirmation) of Instances",
            count
        )

    def allowed(self, request, instance):
        return ((instance.status in project_tables.ACTIVE_STATES or
                 instance.status == 'SHUTOFF') and
                not project_tables.is_deleting(instance))

    def action(self, request, obj_id):
        api.nova.server_migrate(request, obj_id)


class LiveMigrateInstance(policy.PolicyTargetMixin,
                          tables.LinkAction):
    name = "live_migrate"
    verbose_name = _("Live Migrate Instance")
    url = "horizon:admin:instances:live_migrate"
    classes = ("ajax-modal", "btn-migrate")
    policy_rules = (
        ("compute", "os_compute_api:os-migrate-server:migrate_live"),)

    def allowed(self, request, instance):
        return (instance.status in project_tables.ACTIVE_STATES and
                not project_tables.is_deleting(instance))


class AdminUpdateRow(project_tables.UpdateRow):
    def get_data(self, request, instance_id):
        instance = super(AdminUpdateRow, self).get_data(request, instance_id)
        try:
            tenant = api.keystone.tenant_get(request,
                                             instance.tenant_id,
                                             admin=True)
            instance.tenant_name = getattr(tenant, "name", instance.tenant_id)
        except keystone_exceptions.NotFound:
            instance.tenant_name = None

        return instance


class AdminInstanceFilterAction(tables.FilterAction):
    # Change default name of 'filter' to distinguish this one from the
    # project instances table filter, since this is used as part of the
    # session property used for persisting the filter.
    name = "filter_admin_instances"
    filter_type = "server"
    filter_choices = (
        ('project', _("Project Name ="), True),
        ('tenant_id', _("Project ID ="), True),
        ('host', _("Host Name ="), True),
    ) + project_tables.INSTANCE_FILTER_CHOICES


def get_server_detail_link(obj, request):
    roles=[]
    for role in request.user.roles:
        roles.append(role.get('name'))

    if roles.__contains__('project_manager') or roles.__contains__('user'):
        return get_url_with_pagination(request,
                                    InstancesTable._meta.pagination_param,
                                    InstancesTable._meta.prev_pagination_param,
                                    'horizon:project:instances:detail',
                                    obj.id)
    else : 
        return get_url_with_pagination(
            request, AdminInstancesTable._meta.pagination_param,
            AdminInstancesTable._meta.prev_pagination_param,
            "horizon:admin:instances:detail", obj.id)


class AdminInstancesTable(tables.DataTable):
    TASK_STATUS_CHOICES = (
        (None, True),
        ("none", True)
    )
    STATUS_CHOICES = (
        ("active", True),
        ("shutoff", True),
        ("suspended", True),
        ("paused", True),
        ("error", False),
        ("rescue", True),
        ("shelved", True),
        ("shelved_offloaded", True),
    )
    #tenant = tables.Column("tenant_name", verbose_name=_("Project"))
    
    # NOTE(gabriel): Commenting out the user column because all we have
    # is an ID, and correlating that at production scale using our current
    # techniques isn't practical. It can be added back in when we have names
    # returned in a practical manner by the API.
    # user = tables.Column("user_id", verbose_name=_("User"))
    
    # host = tables.Column("OS-EXT-SRV-ATTR:host",
    #                      verbose_name=_("Host"),
    #                      classes=('nowrap-col',))
    
    name = tables.WrappingColumn("name",
                                 link=get_server_detail_link,
                                 verbose_name=_("Name"))
    image_name = tables.Column("image_name",
                               verbose_name=_("Image Name"))
    ip = tables.Column(project_tables.get_ips,
                       verbose_name=_("IP Address"),
                       attrs={'data-type': "ip"})
    
    # flavor = tables.Column(project_tables.get_flavor,
    #                        sortable=False,
    #                        verbose_name=_("Flavor"))
    
    status = tables.Column(
        "status",
        filters=(title, filters.replace_underscores),
        verbose_name=_("Status"),
        status=True,
        status_choices=STATUS_CHOICES,
        display_choices=project_tables.STATUS_DISPLAY_CHOICES)
    locked = tables.Column(project_tables.render_locked,
                           verbose_name="",
                           sortable=False)
    
    # task = tables.Column("OS-EXT-STS:task_state",
    #                      verbose_name=_("Task"),
    #                      empty_value=project_tables.TASK_DISPLAY_NONE,
    #                      status=True,
    #                      status_choices=TASK_STATUS_CHOICES,
    #                      display_choices=project_tables.TASK_DISPLAY_CHOICES)
    
    state = tables.Column(project_tables.get_power_state,
                          filters=(title, filters.replace_underscores),
                          verbose_name=_("Power State"),
                          display_choices=project_tables.POWER_DISPLAY_CHOICES)
    
    # created = tables.Column("created",
    #                         verbose_name=_("Time since created"),
    #                         filters=(filters.parse_isotime,
    #                                  filters.timesince_sortable),
    #                         attrs={'data-type': 'timesince'})

    class Meta(object):
        name = "instances"
        verbose_name = _("Instances")
        status_columns = ["status"] #"task"]
        # table_actions = (project_tables.DeleteInstance,
        #                 AdminInstanceFilterAction)
        
        row_class = AdminUpdateRow
        # row_actions = (project_tables.ConfirmResize,
        #                project_tables.RevertResize,
        #                AdminEditInstance,
        #                AdminConsoleLink,
        #                AdminLogLink,
        #                project_tables.CreateSnapshot,
        #                project_tables.TogglePause,
        #                project_tables.ToggleSuspend,
        #                project_tables.ToggleShelve,
        #                MigrateInstance,
        #                LiveMigrateInstance,
        #                project_tables.SoftRebootInstance,
        #                project_tables.RebootInstance,
        #                project_tables.RebuildInstance,
        #                project_tables.StopInstance,
        #                project_tables.DeleteInstance)

class InstancesTable(tables.DataTable):
    TASK_STATUS_CHOICES = (
        (None, True),
        ("none", True)
    )
    STATUS_CHOICES = (
        ("active", True),
        ("shutoff", True),
        ("suspended", True),
        ("paused", True),
        ("error", False),
        ("rescue", True),
        ("shelved", True),
        ("shelved_offloaded", True),
    )
    name = tables.WrappingColumn("name",
                                 link=get_server_detail_link,
                                 verbose_name=_("Instance Name"))
    image_name = tables.WrappingColumn("image_name",
                                       verbose_name=_("Image Name"))
    ip = tables.Column(project_tables.get_ips,
                       verbose_name=_("IP Address"),
                       attrs={'data-type': "ip"})
    # flavor = tables.Column(get_flavor,
    #                        sortable=False,
    #                        verbose_name=_("Flavor"))
    # keypair = tables.Column(get_keyname, verbose_name=_("Key Pair"))
    status = tables.Column("status",
                           filters=(title, filters.replace_underscores),
                           verbose_name=_("Status"),
                           status=True,
                           status_choices=STATUS_CHOICES,
                           display_choices=project_tables.STATUS_DISPLAY_CHOICES)
    # locked = tables.Column(render_locked,
    #                        verbose_name="",
    #                        sortable=False)
    # az = tables.Column("availability_zone",
    #                    verbose_name=_("Availability Zone"))
    # task = tables.Column("OS-EXT-STS:task_state",
    #                      verbose_name=_("Task"),
    #                      empty_value=TASK_DISPLAY_NONE,
    #                      status=True,
    #                      status_choices=TASK_STATUS_CHOICES,
    #                      display_choices=TASK_DISPLAY_CHOICES)
    state = tables.Column(project_tables.get_power_state,
                          filters=(title, filters.replace_underscores),
                          verbose_name=_("Power State"),
                          display_choices=project_tables.POWER_DISPLAY_CHOICES)
    # created = tables.Column("created",
    #                         verbose_name=_("Time since created"),
    #                         filters=(filters.parse_isotime,
    #                                  filters.timesince_sortable),
    #                         attrs={'data-type': 'timesince'})

    class Meta(object):
        name = "instances"
        verbose_name = _("Instances")
        status_columns = ["status", "task"]
        row_class = project_tables.UpdateRow
        # table_actions_menu = (StartInstance, StopInstance, SoftRebootInstance)
        # launch_actions = ()
        # if getattr(settings, 'LAUNCH_INSTANCE_LEGACY_ENABLED', False):
        #     launch_actions = (LaunchLink,) + launch_actions
        # if getattr(settings, 'LAUNCH_INSTANCE_NG_ENABLED', True):
        #     launch_actions = (LaunchLinkNG,) + launch_actions
        # table_actions = launch_actions + (DeleteInstance,
        #                                   InstancesFilterAction)
        # row_actions = (StartInstance, ConfirmResize, RevertResize,
        #                CreateSnapshot, AssociateIP, DisassociateIP,
        #                AttachInterface, DetachInterface, EditInstance,
        #                AttachVolume, DetachVolume,
        #                UpdateMetadata, DecryptInstancePassword,
        #                EditInstanceSecurityGroups,
        #                EditPortSecurityGroups,
        #                ConsoleLink, LogLink,
        #                TogglePause, ToggleSuspend, ToggleShelve,
        #                ResizeLink, LockInstance, UnlockInstance,
        #                SoftRebootInstance, RebootInstance,
        #                StopInstance, RebuildInstance, DeleteInstance)

def user_link(datum):
    return urls.reverse("horizon:identity:users:detail",
                        args=(datum.user_id,))


class AdminAuditTable(audit_tables.AuditTable):
    user_id = tables.Column('user_id', verbose_name=_('User ID'),
                            link=user_link)

    class Meta(object):
        name = 'audit'
        verbose_name = _('Instance Action List')


################
### RESOURCE ###
################

class AdminHypervisorsTable(tables.DataTable):
    hostname = tables.WrappingColumn("hypervisor_hostname",
                                     link="horizon:admin:hypervisors:detail",
                                     verbose_name=_("Hostname"))

    # hypervisor_type = tables.Column("hypervisor_type",
    #                                 verbose_name=_("Type"))

    vcpus_used = tables.Column("vcpus_used",
                               verbose_name=_("VCPUs (used)"))

    vcpus = tables.Column("vcpus",
                          verbose_name=_("VCPUs (total)"))

    memory_used = tables.Column('memory_mb_used',
                                verbose_name=_("RAM (used)"),
                                attrs={'data-type': 'size'},
                                filters=(sizeformat.mb_float_format,))

    memory = tables.Column('memory_mb',
                           verbose_name=_("RAM (total)"),
                           attrs={'data-type': 'size'},
                           filters=(sizeformat.mb_float_format,))

    # local_used = tables.Column('local_gb_used',
    #                            verbose_name=_("Local Storage (used)"),
    #                            attrs={'data-type': 'size'},
    #                            filters=(sizeformat.diskgbformat,))

    # local = tables.Column('local_gb',
    #                       verbose_name=_("Local Storage (total)"),
    #                       attrs={'data-type': 'size'},
    #                       filters=(sizeformat.diskgbformat,))

    # running_vms = tables.Column("running_vms",
    #                             verbose_name=_("Instances"))

    def get_object_id(self, hypervisor):
        return "%s_%s" % (hypervisor.id,
                          hypervisor.hypervisor_hostname)

    class Meta(object):
        name = "hypervisors"
        verbose_name = _("Hypervisors")


class AdminHypervisorInstancesTable(tables.DataTable):
    name = tables.WrappingColumn("name",
                                 link="horizon:admin:instances:detail",
                                 verbose_name=_("Instance Name"))

    instance_id = tables.Column("uuid",
                                verbose_name=_("Instance ID"))

    def get_object_id(self, server):
        return server['uuid']

    class Meta(object):
        name = "hypervisor_instances"
        verbose_name = _("Hypervisor Instances")


################
###   USER   ###
################

ENABLE = 0
DISABLE = 1
KEYSTONE_V2_ENABLED = api.keystone.VERSIONS.active < 3


class CreateUserLink(tables.LinkAction):
    name = "create"
    verbose_name = _("Create User")
    url = "horizon:identity:users:create"
    classes = ("ajax-modal",)
    icon = "plus"
    policy_rules = (('identity', 'identity:create_grant'),
                    ("identity", "identity:create_user"),
                    ("identity", "identity:list_roles"),
                    ("identity", "identity:list_projects"),)

    def allowed(self, request, user):
        return api.keystone.keystone_can_edit_user()


class EditUserLink(policy.PolicyTargetMixin, tables.LinkAction):
    name = "edit"
    verbose_name = _("Edit")
    url = "horizon:identity:users:update"
    classes = ("ajax-modal",)
    icon = "pencil"
    policy_rules = (("identity", "identity:update_user"),
                    ("identity", "identity:list_projects"),)
    policy_target_attrs = (("user_id", "id"),
                           ("target.user.domain_id", "domain_id"),)

    def allowed(self, request, user):
        return api.keystone.keystone_can_edit_user()


class ChangePasswordLink(tables.LinkAction):
    name = "change_password"
    verbose_name = _("Change Password")
    url = "horizon:identity:users:change_password"
    classes = ("ajax-modal",)
    icon = "key"

    def allowed(self, request, user):
        return api.keystone.keystone_can_edit_user()


class ToggleEnabled(policy.PolicyTargetMixin, tables.BatchAction):
    name = "toggle"

    @staticmethod
    def action_present(count):
        return (
            ungettext_lazy(
                u"Enable User",
                u"Enable Users",
                count
            ),
            ungettext_lazy(
                u"Disable User",
                u"Disable Users",
                count
            ),
        )

    @staticmethod
    def action_past(count):
        return (
            ungettext_lazy(
                u"Enabled User",
                u"Enabled Users",
                count
            ),
            ungettext_lazy(
                u"Disabled User",
                u"Disabled Users",
                count
            ),
        )
    classes = ("btn-toggle",)
    policy_rules = (("identity", "identity:update_user"),)
    policy_target_attrs = (("user_id", "id"),
                           ("target.user.domain_id", "domain_id"))

    def allowed(self, request, user=None):
        if (not api.keystone.keystone_can_edit_user() or
                user.id == request.user.id):
            return False

        self.enabled = True
        if not user:
            return self.enabled
        self.enabled = user.enabled
        if self.enabled:
            self.current_present_action = DISABLE
        else:
            self.current_present_action = ENABLE
        return True

    def action(self, request, obj_id):
        if self.enabled:
            api.keystone.user_update_enabled(request, obj_id, False)
            self.current_past_action = DISABLE
        else:
            api.keystone.user_update_enabled(request, obj_id, True)
            self.current_past_action = ENABLE


class DeleteUsersAction(policy.PolicyTargetMixin, tables.DeleteAction):
    @staticmethod
    def action_present(count):
        return ungettext_lazy(
            u"Delete User",
            u"Delete Users",
            count
        )

    @staticmethod
    def action_past(count):
        return ungettext_lazy(
            u"Deleted User",
            u"Deleted Users",
            count
        )
    policy_rules = (("identity", "identity:delete_user"),)

    def allowed(self, request, datum):
        if not api.keystone.keystone_can_edit_user() or \
                (datum and datum.id == request.user.id):
            return False
        return True

    def delete(self, request, obj_id):
        api.keystone.user_delete(request, obj_id)


class UserFilterAction(tables.FilterAction):
    if api.keystone.VERSIONS.active < 3:
        filter_type = "query"
    else:
        filter_type = "server"
        filter_choices = (("name", _("User Name ="), True),
                          ("id", _("User ID ="), True),
                          ("enabled", _("Enabled ="), True, _('e.g. Yes/No')))


class UpdateRow(tables.Row):
    ajax = True

    def get_data(self, request, user_id):
        user_info = api.keystone.user_get(request, user_id, admin=True)
        return user_info


class UsersTable(tables.DataTable):
    STATUS_CHOICES = (
        ("true", True),
        ("false", False)
    )
    name = tables.WrappingColumn('name',
                                 link="horizon:identity:users:detail",
                                 verbose_name=_('Student Name'),
                                 form_field=forms.CharField(required=False))
    # description = tables.Column(lambda obj: getattr(obj, 'description', None),
    #                             verbose_name=_('Description'),
    #                             hidden=KEYSTONE_V2_ENABLED,
    #                             form_field=forms.CharField(
    #                                 widget=forms.Textarea(attrs={'rows': 4}),
    #                                 required=False))
    
    # email = tables.Column(lambda obj: getattr(obj, 'email', None),
    #                       verbose_name=_('Email'),
    #                       form_field=forms.EmailField(required=False),
    #                       filters=(lambda v: defaultfilters
    #                                .default_if_none(v, ""),
    #                                defaultfilters.escape,
    #                                defaultfilters.urlize)
    #                       )
    
    # Default tenant is not returned from Keystone currently.
    # default_tenant = tables.Column('default_tenant',
    #                                verbose_name=_('Default Project'))
    id = tables.Column('id', verbose_name=_('Student Number'),
                       attrs={'data-type': 'uuid'})
    enabled = tables.Column('enabled', verbose_name=_('Enabled'),
                            status=True,
                            status_choices=STATUS_CHOICES,
                            filters=(defaultfilters.yesno,
                                     defaultfilters.capfirst),
                            empty_value="False")

    # if api.keystone.VERSIONS.active >= 3:
    #     domain_name = tables.Column('domain_name',
    #                                 verbose_name=_('Domain Name'),
    #                                 attrs={'data-type': 'uuid'})

    class Meta(object):
        name = "users"
        verbose_name = _("Students")
        #  row_actions = (EditUserLink, ChangePasswordLink, ToggleEnabled,
        #                DeleteUsersAction)
        # table_actions = (UserFilterAction, CreateUserLink, DeleteUsersAction)
        row_class = UpdateRow