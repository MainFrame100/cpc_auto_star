from app import create_app

app = create_app()

if __name__ == '__main__':
    # Запускаем сервер разработки Flask
    # debug=True включает автоматическую перезагрузку при изменениях кода
    # и подробные сообщения об ошибках в браузере.
    # ВНИМАНИЕ: Никогда не используйте debug=True в продакшене!
    app.run(debug=True) 