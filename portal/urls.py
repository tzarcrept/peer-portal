from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('analytics/', views.project_dashboard, name='project_dashboard'),
    path('analytics/<str:project_name>/', views.project_dashboard, name='project_dashboard_named'),
    path('insight/<str:project_name>/refresh/', views.refresh_insight, name='refresh_insight'),
    path('repository/', views.repository, name='repository'),
    path('project/new/', views.project_form, name='add_project'),
    path('project/<str:project_name>/edit/', views.project_form, name='edit_project'),
    path('project/<str:project_name>/delete/', views.delete_project, name='delete_project'),
    path('download-csv/', views.download_csv, name='download_csv'),
    path('download-analytics-csv/', views.download_analytics_csv, name='download_analytics_csv'),
]
