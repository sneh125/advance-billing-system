from django.shortcuts import render

def login_view(request):
    return render(request, 'accounts/login.html')
# Create your views here.
