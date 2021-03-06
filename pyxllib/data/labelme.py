#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @Author : 陈坤泽
# @Email  : 877362867@qq.com
# @Date   : 2020/08/15 00:59


from tqdm import tqdm
import json
import ujson
import copy

from pyxllib.prog.deprecatedlib import deprecated
import pandas as pd
import numpy as np

from pyxllib.prog.pupil import DictTool
from pyxllib.debug.specialist import get_xllog, Iterate, dprint
from pyxllib.file.specialist import File, Dir, PathGroups, get_encoding
from pyxllib.prog.specialist import mtqdm
from pyxllib.cv.expert import PilImg
from pyxllib.algo.geo import ltrb2xywh, rect_bounds, warp_points, resort_quad_points, rect2polygon, get_warp_mat

__0_basic = """
这里可以写每个模块注释
"""


class BasicLabelDataset:
    """ 一张图一份标注文件的一些基本操作功能 """

    def __init__(self, root, relpath2data=None, *, reads=True, prt=False, fltr=None, slt=None, extdata=None):
        """
        :param root: 数据所在根目录
        :param dict[str, readed_data] relpath2data: {relpath: data1, 'a/1.txt': data2, ...}
            如果未传入data具体值，则根据目录里的情况自动初始化获得data的值

            relpath是对应的File标注文件的相对路径字符串
            data1, data2 是读取的标注数据，根据不同情况，会存成不同格式
                如果是json则直接保存json内存对象结构
                如果是txt可能会进行一定的结构化解析存储
        :param extdata: 可以存储一些扩展信息内容
        :param fltr: filter的缩写，PathGroups 的过滤规则。一般用来进行图片匹配。
            None，没有过滤规则，就算不存在slt格式的情况下，也会保留分组
            'json'等字符串规则, 使用 select_group_which_hassuffix，必须含有特定后缀的分组
            judge(k, v)，自定义函数规则
        :param slt: select的缩写，要选中的标注文件后缀格式
            如果传入slt参数，该 Basic 基础类只会预设好 file 参数，数据部分会置 None，需要后续主动读取

        >> BasicLabelData('textGroup/aabb', {'a.json': ..., 'a/1.json': ...})
        >> BasicLabelData('textGroup/aabb', slt='json')
        >> BasicLabelData('textGroup/aabb', fltr='jpg', slt='json')  # 只获取有对应jpg图片的json文件
        >> BasicLabelData('textGroup/aabb', fltr='jpg|png', slt='json')
        """

        # 1 基础操作
        root = Dir(root)
        self.root, self.rp2data, self.extdata = root, relpath2data or {}, extdata or {}

        if relpath2data is not None or slt is None:
            return

        # 2 如果没有默认data数据，以及传入slt参数，则需要使用默认文件关联方式读取标注
        relpath2data = {}
        gs = PathGroups.groupby(Dir(root).select_files('**/*'))
        if isinstance(fltr, str):
            gs = gs.select_group_which_hassuffix(fltr)
        elif callable(fltr):
            gs = gs.select_group(fltr)
        self.pathgs = gs

        # 3 读取数据
        for stem, suffixs in tqdm(gs.data.items(), f'{self.__class__.__name__}读取数据', disable=not prt):
            f = File(stem, suffix=slt)
            if reads and f:
                # dprint(f)  # 空json会报错：json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
                relpath2data[f.relpath(self.root)] = f.read()
            else:
                relpath2data[f.relpath(self.root)] = None

        self.rp2data = relpath2data

    def __len__(self):
        return len(self.rp2data)

    def read(self, relpath, **kwargs):
        """
        :param relpath: 必须是斜杠表示的相对路径 'a/1.txt'、'b/2.json'
        """
        self.rp2data[relpath] = File(relpath, self.root).read(**kwargs)

    def reads(self, prt=False, **kwargs):
        """ 为了性能效率，初始化默认不会读取数据，需要调用reads才会开始读取数据 """
        for k in tqdm(self.rp2data.keys(), f'读取{self.__class__.__name__}数据', disable=not prt):
            self.rp2data[k] = File(k, self.root).read(**kwargs)

    def write(self, relpath, **kwargs):
        """
        :param relpath: 必须是斜杠表示的相对路径 'a/1.txt'、'b/2.json'
        """
        data = self.rp2data[relpath]
        file = File(relpath, self.root)
        if file:  # 如果文件存在，要遵循原有的编码规则
            with open(str(file), 'rb') as f:
                bstr = f.read()
            encoding = get_encoding(bstr)
            kwargs['encoding'] = encoding
            kwargs['if_exists'] = 'delete'
            file.write(data, **kwargs)
        else:  # 否则直接写入
            file.write(data, **kwargs)

    def writes(self, *, max_workers=8, prt=False, **kwargs):
        """ 重新写入每份标注文件

        可能是内存里修改了数据，需要重新覆盖
        也可能是从coco等其他格式初始化，转换而来的内存数据，需要生成对应的新标注文件
        """
        mtqdm(lambda x: self.write(x, **kwargs), self.rp2data.keys(), desc=f'{self.__class__.__name__}写入标注数据',
              max_workers=max_workers, disable=not prt)


__1_labelme = """
"""

# 我自己按照“红橙黄绿蓝靛紫”的顺序展示
LABEL_COLORMAP7 = [(0, 0, 0), (255, 0, 0), (255, 125, 0), (255, 255, 0),
                   (0, 255, 0), (0, 0, 255), (0, 255, 255), (255, 0, 255)]


def is_labelme_json_data(data):
    """ 是labelme的标注格式
    :param data: dict
    :return: True or False
    """
    has_keys = set('version flags shapes imagePath imageData imageHeight imageWidth'.split())
    return not (has_keys - data.keys())


def reduce_labelme_jsonfile(jsonpath):
    """ 删除imageData """
    p = str(jsonpath)

    with open(p, 'rb') as f:
        bstr = f.read()
    encoding = get_encoding(bstr)
    data = ujson.loads(bstr.decode(encoding=encoding))

    if is_labelme_json_data(data) and data['imageData']:
        data['imageData'] = None
        File(p).write(data, encoding=encoding, if_exists='replace')


class ToLabelmeJson:
    """ 标注格式转label形式

    初始化最好带有图片路径，能获得一些相关有用的信息
    然后自定义实现一个 get_data 接口，实现self.data的初始化，运行完可以从self.data取到字典数据
        根据需要可以定制自己的shape，修改get_shape函数
    可以调用write写入文件

    document: https://www.yuque.com/xlpr/pyxllib/ks5h4o
    """

    # 可能有其他人会用我库的高级接口，不应该莫名其妙报警告。除非我先实现自己库内该功能的剥离
    # @deprecated(reason='建议使用LabelmeData实现')
    def __init__(self, imgpath):
        """
        :param imgpath: 可选参数图片路径，强烈建议要输入，否则建立的label json会少掉图片宽高信息
        """
        self.imgpath = File(imgpath)
        # 读取图片数据，在一些转换规则比较复杂，有可能要用到原图数据
        if self.imgpath:
            # 一般都只需要获得尺寸，用pil读取即可，速度更快，不需要读取图片rgb数据
            self.img = PilImg(self.imgpath)
        else:
            self.img = None
        self.data = self.get_data_base()  # 存储json的字典数据

    def get_data(self, infile):
        """ 格式转换接口函数，继承的类需要自己实现这个方法

        :param infile: 待解析的标注数据
        """
        raise NotImplementedError('get_data方法必须在子类中实现')

    def get_data_base(self, name='', height=0, width=0):
        """ 获得一个labelme标注文件的框架 （这是标准结构，也可以自己修改定制）

        如果初始化时没有输入图片，也可以这里传入name等的值
        """
        # 1 默认属性，和图片名、尺寸
        if self.imgpath:
            name = self.imgpath.name
            height, width = self.img.size()
        # 2 构建结构框架
        data = {'version': '4.5.6',
                'flags': {},
                'shapes': [],
                'imagePath': name,
                'imageData': None,
                'imageWidth': width,
                'imageHeight': height,
                }
        return data

    def get_shape(self, label, points, shape_type=None, dtype=None, group_id=None, **kwargs):
        """ 最基本的添加形状功能

        :param shape_type: 会根据points的点数量，智能判断类型，默认一般是polygon
            其他需要自己指定的格式：line、circle
        :param dtype: 可以重置points的存储数值类型，一般是浮点数，可以转成整数更精简
        :param group_id: 本来是用来分组的，但其值会以括号的形式添加在label后面，可以在可视化中做一些特殊操作
        """
        # 1 优化点集数据格式
        points = np.array(points, dtype=dtype).reshape(-1, 2).tolist()
        # 2 判断形状类型
        if shape_type is None:
            m = len(points)
            if m == 1:
                shape_type = 'point'
            elif m == 2:
                shape_type = 'rectangle'
            elif m >= 3:
                shape_type = 'polygon'
            else:
                raise ValueError
        # 3 创建标注
        shape = {'flags': {},
                 'group_id': group_id,
                 'label': str(label),
                 'points': points,
                 'shape_type': shape_type}
        shape.update(kwargs)
        return shape

    def get_shape2(self, **kwargs):
        """ 完全使用字典的接口形式 """
        label = kwargs.get('label', '')
        points = kwargs['points']  # 这个是必须要有的字段
        kw = copy.deepcopy(kwargs)
        del kw['label']
        del kw['points']
        return self.get_shape(label, points, **kw)

    def add_shape(self, *args, **kwargs):
        self.data['shapes'].append(self.get_shape(*args, **kwargs))

    def add_shape2(self, **kwargs):
        self.data['shapes'].append(self.get_shape2(**kwargs))

    def write(self, dst=None, if_exists='replace'):
        """
        :param dst: 往dst目标路径存入json文件，默认名称在self.imgpath同目录的同名json文件
        :return: 写入后的文件路径
        """
        if dst is None and self.imgpath:
            dst = self.imgpath.with_suffix('.json')
        # 官方json支持indent=None的写法，但是ujson必须要显式写indent=0
        return File(dst).write(self.data, if_exists=if_exists, indent=0)

    @classmethod
    def create_json(cls, imgpath, annotation):
        """ 输入图片路径p，和对应的annotation标注数据（一般是对应目录下txt文件） """
        try:
            obj = cls(imgpath)
        except TypeError as e:  # 解析不了的输出错误日志
            get_xllog().exception(e)
            return
        obj.get_data(annotation)
        obj.write()  # 保存json文件到img对应目录下

    @classmethod
    def main_normal(cls, imdir, labeldir=None, label_file_suffix='.txt'):
        """ 封装更高层的接口，输入目录，直接标注目录下所有图片

        :param imdir: 图片路径
        :param labeldir: 标注数据路径，默认跟imdir同目录
        :return:
        """
        ims = Dir(imdir).select_files(['*.jpg', '*.png'])
        if not labeldir: labeldir = imdir
        txts = [File(f.stem, labeldir, suffix=label_file_suffix) for f in ims]
        cls.main_pair(ims, txts)

    @classmethod
    def main_pair(cls, images, labels):
        """ 一一配对匹配处理 """
        Iterate(zip(images, labels)).run(lambda x: cls.create_json(x[0], x[1]),
                                         pinterval='20%', max_workers=8)


class Quad2Labelme(ToLabelmeJson):
    """ 四边形类标注转labelme """

    def get_data(self, infile):
        lines = File(infile).read().splitlines()
        for line in lines:
            # 一般是要改这里，每行数据的解析规则
            vals = line.split(',', maxsplit=8)
            if len(vals) < 9: continue
            pts = [int(v) for v in vals[:8]]  # 点集
            label = vals[-1]  # 标注的文本
            # get_shape还有shape_type形状参数可以设置
            #  如果是2个点的矩形，或者3个点以上的多边形，会自动判断，不用指定shape_type
            self.add_shape(label, pts)


class LabelmeDict:
    """ Labelme格式的字典数据

    这里的成员函数基本都是原地操作
    """

    @classmethod
    def gen_data(cls, imfile=None, **kwargs):
        """ 主要框架结构
        :param imfile: 可以传入一张图片路径
        """
        # 1 传入图片路径的初始化
        if imfile:
            file = File(imfile)
            name = file.name
            img = PilImg(str(file))
            height, width = img.size()
        else:
            name, height, width = '', 0, 0

        # 2 字段值
        data = {'version': '4.5.7',
                'flags': {},
                'shapes': [],
                'imagePath': name,
                'imageData': None,
                'imageWidth': width,
                'imageHeight': height,
                }
        if kwargs:
            data.update(kwargs)
        return data

    @classmethod
    def gen_shape(cls, label, points, shape_type=None, dtype=None, group_id=None, **kwargs):
        """ 最基本的添加形状功能

        :param shape_type: 会根据points的点数量，智能判断类型，默认一般是polygon
            其他需要自己指定的格式：line、circle
        :param dtype: 可以重置points的存储数值类型，一般是浮点数，可以转成整数更精简
        :param group_id: 本来是用来分组的，但其值会以括号的形式添加在label后面，可以在可视化中做一些特殊操作
        """
        # 1 优化点集数据格式
        points = np.array(points, dtype=dtype).reshape(-1, 2).tolist()
        # 2 判断形状类型
        if shape_type is None:
            m = len(points)
            if m == 1:
                shape_type = 'point'
            elif m == 2:
                shape_type = 'rectangle'
            elif m >= 3:
                shape_type = 'polygon'
            else:
                raise ValueError
        # 3 创建标注
        shape = {'flags': {},
                 'group_id': group_id,
                 'label': str(label),
                 'points': points,
                 'shape_type': shape_type}
        shape.update(kwargs)
        return shape

    @classmethod
    def gen_shape2(cls, **kwargs):
        """ 完全使用字典的接口形式 """
        label = kwargs.get('label', '')
        points = kwargs['points']  # 这个是必须要有的字段
        kw = copy.deepcopy(kwargs)
        del kw['label']
        del kw['points']
        return cls.gen_shape(label, points, **kw)

    @classmethod
    def reduce(cls, lmdict, *, inplace=True):
        if not inplace:
            lmdict = copy.deepcopy(lmdict)

        lmdict['imageData'] = None
        return lmdict

    @classmethod
    def flip_points(cls, lmdict, direction, *, inplace=True):
        """
        :param direction: points的翻转方向
            1表示顺时针转90度，2表示顺时针转180度...
            -1表示逆时针转90度，...
        :return:
        """
        if not inplace:
            lmdict = copy.deepcopy(lmdict)

        w, h = lmdict['imageWidth'], lmdict['imageHeight']
        pts = [[[0, 0], [w, 0], [w, h], [0, h]],
               [[h, 0], [h, w], [0, w], [0, 0]],
               [[w, h], [0, h], [0, 0], [w, 0]],
               [[0, w], [0, 0], [h, 0], [h, w]]]
        warp_mat = get_warp_mat(pts[0], pts[direction % 4])

        if direction % 2:
            lmdict['imageWidth'], lmdict['imageHeight'] = lmdict['imageHeight'], lmdict['imageWidth']
        shapes = lmdict['shapes']
        for i, shape in enumerate(shapes):
            pts = [warp_points(x, warp_mat)[0].tolist() for x in shape['points']]
            if shape['shape_type'] == 'rectangle':
                pts = resort_quad_points(rect2polygon(pts))
                shape['points'] = [pts[0], pts[2]]
            elif shape['shape_type'] == 'polygon' and len(pts) == 4:
                shape['points'] = resort_quad_points(pts)
            else:  # 其他形状暂不处理，也不报错
                pass
        return lmdict

    @classmethod
    def update_labelattr(cls, lmdict, *, points=False, inplace=True):
        """

        :param points: 是否更新labelattr中的points、bbox等几何信息
            并且在无任何几何信息的情况下，增设points
        """
        if not inplace:
            lmdict = copy.deepcopy(lmdict)

        for shape in lmdict['shapes']:
            # 1 属性字典，至少先初始化一个label属性
            labelattr = DictTool.json_loads(shape['label'], 'label')
            # 2 填充其他扩展属性值
            keys = set(shape.keys())
            stdkeys = set('label,points,group_id,shape_type,flags'.split(','))
            for k in (keys - stdkeys):
                labelattr[k] = shape[k]
                del shape[k]  # 要删除原有的扩展字段值

            # 3 处理points等几何信息
            if points:
                if 'bbox' in labelattr:
                    labelattr['bbox'] = ltrb2xywh(rect_bounds(shape['points']))
                else:
                    labelattr['points'] = shape['points']

            # + 写回shape
            shape['label'] = json.dumps(labelattr, ensure_ascii=False)
        return lmdict


class LabelmeDataset(BasicLabelDataset):
    def __init__(self, root, relpath2data=None, *, reads=True, prt=False, fltr='json', slt='json', extdata=None):
        """
        :param root: 文件根目录
        :param relpath2data: {jsonfile: lmdict, ...}，其中 lmdict 为一个labelme文件格式的标准内容
            如果未传入data具体值，则根据目录里的情况自动初始化获得data的值

            210602周三16:26，为了工程等一些考虑，删除了 is_labelme_json_data 的检查
                尽量通过 fltr、slt 的机制选出正确的 json 文件
        """
        super().__init__(root, relpath2data, reads=reads, prt=prt, fltr=fltr, slt=slt, extdata=extdata)

        # 已有的数据已经读取了，这里要补充空labelme标注
        for stem, suffixs in tqdm(self.pathgs.data.items(), f'{self.__class__.__name__}优化数据', disable=not prt):
            f = File(stem, suffix=slt)
            if reads and not f:
                self.rp2data[f.relpath(self.root)] = LabelmeDict.gen_data(File(stem, suffix=suffixs[0]))

    def reduces(self):
        """ 移除imageData字段值 """
        for _, lmdict in self.rp2data:
            LabelmeDict.reduce(lmdict)

    def update_labelattrs(self, *, points=False):
        """ 将shape['label'] 升级为字典类型

        可以处理旧版不动产标注 content_class 等问题
        """
        for jsonfile, lmdict in self.rp2data.items():
            LabelmeDict.update_labelattr(lmdict, points=points)

    def to_excel(self, savepath):
        """ 转成dataframe表格查看

        这个细节太多，可以 labelme 先转 coco 后，借助 coco 转 excel
            coco 里会给 image、box 编号，能显示一些补充属性
        """
        from pyxllib.data.coco import CocoParser
        gt_dict = self.to_coco_gt_dict()
        CocoParser(gt_dict).to_excel(savepath)

    @classmethod
    def plot(self, img, lmdict):
        """ 将标注画成静态图 """
        raise NotImplementedError

    def to_coco_gt_dict(self, categories=None):
        """ 将labelme转成 coco gt 标注的格式

        分两种大情况
        1、一种是raw原始数据转labelme标注后，首次转coco格式，这种编号等相关数据都可以重新生成
            raw_data --可视化--> labelme --转存--> coco
        2、还有种原来就是coco，转labelme修改标注后，又要再转回coco，这种应该尽量保存原始值
            coco --> labelme --手动修改--> labelme' --> coco'
            这种在coco转labelme时，会做一些特殊标记，方便后续转回coco
        3、 1, 2两种情况是可以连在一起，然后形成 labelme 和 coco 之间的多次互转的

        :param categories: 类别
            默认只设一个类别 {'id': 0, 'name': 'text', 'supercategory'}
            支持自定义，所有annotations的category_id
        :return: gt_dict
            注意，如果对文件顺序、ann顺序有需求的，请先自行操作self.data数据后，再调用该to_coco函数
            对image_id、annotation_id有需求的，需要使用CocoData进一步操作
        """
        from pyxllib.data.coco import CocoGtData

        if not categories:
            if 'categories' in self.extdata:
                # coco 转过来的labelme，存储有原始的 categories
                categories = self.extdata['categories']
            else:
                categories = [{'id': 0, 'name': 'text', 'supercategory': ''}]

        # 1 第一轮遍历：结构处理 jsonfile, lmdict --> data（image, shapes）
        img_id, ann_id, data = 0, 0, []
        for jsonfile, lmdict in self.rp2data.items():
            # 1.0 升级为字典类型
            lmdict = LabelmeDict.update_labelattr(lmdict, points=True)

            for sp in lmdict['shapes']:  # label转成字典
                sp['label'] = json.loads(sp['label'])

            # 1.1 找shapes里的image
            image = None
            # 1.1.1 xltype='image'
            for sp in filter(lambda x: x.get('xltype', None) == 'image', lmdict['shapes']):
                image = DictTool.json_loads(sp['label'])
                if not image:
                    raise ValueError(sp['label'])
                # TODO 删除 coco_eval 等字段？
                del image['xltype']
                break
            # 1.1.2 shapes里没有图像级标注则生成一个
            if image is None:
                # TODO file_name 加上相对路径？
                image = CocoGtData.gen_image(-1, lmdict['imagePath'],
                                             lmdict['imageHeight'], lmdict['imageWidth'])
            img_id = max(img_id, image.get('id', -1))

            # 1.2 遍历shapes
            shapes = []
            for sp in lmdict['shapes']:
                label = sp['label']
                if 'xltype' not in label:
                    # 普通的标注框
                    d = sp['label'].copy()
                    # DictTool.isub_(d, '')
                    ann_id = max(ann_id, d.get('id', -1))
                    shapes.append(d)
                elif label['xltype'] == 'image':
                    # image，图像级标注数据；之前已经处理了，这里可以跳过
                    pass
                elif label['xltype'] == 'seg':
                    # seg，衍生的分割标注框，在转回coco时可以丢弃
                    pass
                else:
                    raise ValueError
            data.append([image, shapes])

        # 2 第二轮遍历：处理id等问题
        images, annotations = [], []
        for image, shapes in data:
            # 2.1 image
            if image.get('id', -1) == -1:
                img_id += 1
                image['id'] = img_id
            images.append(image)

            # 2.2 annotations
            for sp in shapes:
                sp['image_id'] = img_id
                if sp.get('id', -1) == -1:
                    ann_id += 1
                    sp['id'] = ann_id
                # 如果没有框类别，会默认设置一个。 （强烈建议外部业务功能代码自行设置好category_id）
                if 'category_id' not in sp:
                    sp['category_id'] = categories[0]['id']
                DictTool.isub(sp, ['category_name'])
                ann = CocoGtData.gen_annotation(**sp)
                annotations.append(ann)

        # 3 result
        gt_dict = CocoGtData.gen_gt_dict(images, annotations, categories)
        return gt_dict
