import cv2, glob, requests, os
from pyzbar.pyzbar import decode

dirpath = os.path.dirname(__file__)
picpath = os.path.join(dirpath, 'pic/')


def read_barcode(flink,chat_id):
    myfile = requests.get(flink)
    open(picpath+str(chat_id)+'.jpg', 'wb').write(myfile.content)

    image = cv2.imread(picpath+str(chat_id)+'.jpg')
    detectedBarcodes = decode(image)

    if not detectedBarcodes:
        # Удалим файлы после использования
       # for file in glob.glob(picpath+str(chat_id)+'.jpg'):
       #     os.remove(file)
            return ('No')
    else:
        for barcode in detectedBarcodes:
            (x, y, w, h) = barcode.rect
            cv2.rectangle(image, (x, y), (x + w, y + h), (255, 0, 0), 5)
            # Удалим файлы после использования
            for file in glob.glob(picpath + str(chat_id) + '.jpg'):
                os.remove(file)

            return (barcode.data)