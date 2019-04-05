# The name of the dashboard to be added to HORIZON['dashboards']. Required.
DASHBOARD = 'main'

# If set to True, this dashboard will be set as the default dashboard.
DEFAULT = True

# A list of applications to be added to INSTALLED_APPS.
ADD_INSTALLED_APPS = [
    'openstack_dashboard.dashboards.main',
]

ADD_ANGULAR_MODULES = []

AUTO_DISCOVER_STATIC_FILES = True