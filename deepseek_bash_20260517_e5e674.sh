cat > ~/build_android.sh << 'EOF'
#!/bin/bash

# Активируем окружение
source ~/buildozer-env-311/bin/activate

# Устанавливаем переменные для Python
export PATH=~/buildozer-env-311/bin:$PATH
export PYTHONHOME=~/buildozer-env-311
export PYTHONPATH=~/buildozer-env-311/lib/python3.11/site-packages

# Явно указываем пути к Python
export HOSTPYTHON=~/buildozer-env-311/bin/python3.11
export TARGETPYTHON=~/buildozer-env-311/bin/python3.11

# Переходим в проект
cd ~/psprice

# Очищаем предыдущие сборки
rm -rf .buildozer/android/platform/build-*

# Запускаем сборку с явным указанием Python
buildozer android debug
EOF

chmod +x ~/build_android.sh