import json
from datetime import datetime
from io import BytesIO

import cloudscraper
import discord
import asyncio
import requests
from PIL import Image
from attr.exceptions import DefaultAlreadySetError


def load_config():
    with open('config.json', 'r', encoding='utf-8') as file:
        return json.load(file)


def load_user_stats():
    with open("user_stats.json", 'r', encoding='utf-8') as f:
        return json.load(f)


config = load_config()
previous_error_pixels = set()
user_error_stats = load_user_stats()

def m():
    # 创建机器人客户端
    intents = discord.Intents.default()
    intents.message_content = True  # 如果需要读取消息内容，需要启用此意图

    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        client.loop.create_task(schedule_observer(client))

    @client.event
    async def on_message(message):
        if message.author == client.user:
            return
        if message.content.startswith('!rank'):
            await send_stats_leaderboard(message.channel)
        if message.content.startswith('!errorPixels'):
            await send_coordinate(message.channel)
        if message.content.startswith('!rm'):
            await rm_user(message.content[4:],message.channel)
        print(message.content)

    # 使用Token登录机器人
    client.run(config['Token'])
    
async def rm_user(user_id,channel):
    if user_id in user_error_stats:
        name = user_error_stats[user_id]['info']['name']
        del user_error_stats[user_id]
        save_user_stats()
        await channel.send(f"已赦免用户 {user_id} {name}")

async def send_coordinate(channel):
    text = ""
    if len(previous_error_pixels) == 0:
        text += "当前无错误"
        await channel.send(text)
        return
    text = "**错误像素坐标**\n"
    text+="| PxX | PxY |\n"
    text+="|----|----|\n"
    for p in previous_error_pixels:
        text += f"| {p[0]} | {p[1]} |\n"
    await channel.send(text)

async def schedule_observer(client):
    """
    定时执行observer函数
    """
    await client.wait_until_ready()  # 等待机器人完全准备好

    while not client.is_closed():
        try:
            print(f"当前时间: {datetime.now()}")
            await observer(client)
            print(f"观测完成.")
        except Exception as e:
            print(f"Observer执行出错: {e}")

        # 等待60秒
        await asyncio.sleep(10)

f = True
async def observer(client):
    global previous_error_pixels
    global f

    remote_image = download_image(config['TlX'], config['TlY'])
    template_image = load_template(config['Template'])
    if remote_image and template_image:
        # 比较图片并获取不同像素坐标
        different_pixels = compare_images_with_offset(remote_image, template_image,
                                                      config['PxX'], config['PxY'])
        print(f"找到 {len(different_pixels)} 个错误像素:")
        current_error_pixels = set(different_pixels)
        new_errors = current_error_pixels - previous_error_pixels

        if len(new_errors) > 0:
            cropped_image = crop_image(remote_image, template_image,
                                       config['PxX'], config['PxY'])
            await send_to_discord(client, cropped_image, f"当前 {len(different_pixels)} 个错误像素 坏蛋名单统计中...")
            error_stats ,new_error_stats = collect_user_error_statistics(different_pixels)
            if f:
                f = False
            else:
                update_total_user_stats(new_error_stats)
            save_user_stats()
            stats_text = generate_stats_text(error_stats)
            await send_text(client, stats_text)
        elif len(different_pixels) == 0 and len(previous_error_pixels) > 0:
            # 所有错误像素已消除
            print("所有错误像素已清除")
            await send_clear_complete_message(client)
            
        previous_error_pixels = current_error_pixels

async def send_text(client, text):
    """
    将图片和文本发送到配置的Discord频道
    
    Args:
        client: Discord客户端
        text: 要发送的文本
    """
    try:
        for channel_id in config['Channels']:
            channel = client.get_channel(channel_id)

            if not channel:
                print(f"无法找到频道 ID: {channel_id}")
                return

            message_content = f"{text}"
            await channel.send(content=message_content)
            print(f"成功发送消息到频道: {channel.name}")

    except Exception as e:
        print(f"发送到Discord时出错: {e}")


def update_total_user_stats(current_user_stats):
    """
    更新总用户统计信息
    
    Args:
        current_user_stats: 当前轮次的用户统计信息
    """

    for user_id, stats in current_user_stats.items():
        count = stats['count']
        # 累加到总统计中
        if user_id in user_error_stats:
            user_error_stats[user_id]['count'] += count
        else:
            user_error_stats[user_id] = stats

    print(f"更新了 {len(current_user_stats)} 个用户的统计信息")

def save_user_stats():
    """
    将用户统计信息保存到本地文件
    """
    try:
        with open("user_stats.json", 'w', encoding='utf-8') as f:
            json.dump(user_error_stats, f, ensure_ascii=False, indent=2)
        print("用户统计信息已保存")
    except Exception as e:
        print(f"保存用户统计信息时出错: {e}")

async def send_stats_leaderboard(channel):
    """
    发送用户统计排行榜到指定频道
    
    Args:
        channel: 目标频道
    """
    if not user_error_stats:
        await channel.send("暂无用户统计数据。")
        return

    # 按错误数量排序
    sorted_stats =  sorted(user_error_stats.items(),
                           key=lambda item: item[1]['count'],
                           reverse=True)

    # 生成排行榜文本
    leaderboard_text = "**坏蛋榜**\n"

    for i, (user_id, stats) in enumerate(sorted_stats):  # 显示前20名

        if stats['info']['allianceName'] != '':
            leaderboard_text += f"{i+1:2d}. {stats['info']['name']} (ID: {user_id}) - {stats['info']['allianceName']} - {stats['count']} 个错误像素\n"
        else:
            leaderboard_text += f"{i+1:2d}. {stats['info']['name']} (ID: {user_id}) - {stats['count']} 个错误像素\n"


    try:
        await channel.send(leaderboard_text)
        print(f"已发送排行榜到频道: {channel.name}")
    except Exception as e:
        print(f"发送排行榜时出错: {e}")


async def send_clear_complete_message(client):
    """
    发送清除完成消息
    
    Args:
        client: Discord客户端
    """
    try:
        # 遍历所有配置的频道
        for channel_id in config['Channels']:
            # 获取频道
            channel = client.get_channel(channel_id)

            if not channel:
                print(f"无法找到频道 ID: {channel_id}")
                continue

            try:
                # 发送清除完成消息
                message_content = "✅ 所有错误像素已清除完成！"
                await channel.send(content=message_content)
                print(f"成功发送清除完成消息到频道: {channel.name} (ID: {channel_id})")
            except discord.Forbidden:
                print(f"没有权限发送消息到频道: {channel.name} (ID: {channel_id})")
            except discord.HTTPException as e:
                print(f"发送消息到频道 {channel.name} (ID: {channel_id}) 时出错: {e}")
            except Exception as e:
                print(f"发送消息到频道 {channel.name} (ID: {channel_id}) 时发生未知错误: {e}")

    except Exception as e:
        print(f"发送清除完成消息时出错: {e}")


async def send_to_discord(client, image, text):
    """
    将图片和文本发送到配置的Discord频道
    
    Args:
        client: Discord客户端
        image: PIL图片对象
        text: 要发送的文本
    """
    try:
        for channel_id in config['Channels']:
            channel = client.get_channel(channel_id)

            if not channel:
                print(f"无法找到频道 ID: {channel_id}")
                return

            # 将图片转换为字节流
            img_byte_arr = BytesIO()
            image.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)

            # 创建discord文件对象
            discord_file = discord.File(img_byte_arr, filename='cropped_image.png')

            # 发送消息，包含@everyone
            message_content = f"@everyone\n\n{text}"

            await channel.send(content=message_content, file=discord_file)
            print(f"成功发送消息到频道: {channel.name}")

    except Exception as e:
        print(f"发送到Discord时出错: {e}")


def generate_stats_text(user_error_stats):
    """
    生成统计文本
    
    Args:
        user_error_stats: 用户统计信息
    
    Returns:
        str: 格式化的统计文本
    """
    if not user_error_stats:
        return "未找到错误像素或无法获取用户信息。"

    # 按错误数量排序
    sorted_stats = sorted(user_error_stats.items(),
                          key=lambda x: x[1]['count'], reverse=True)

    text = f"抓到 {len(sorted_stats)} 个破坏者:\n\n"

    for i, (user_id, stats) in enumerate(sorted_stats):  # 只显示前10个
        user_info = stats['info']
        name = user_info.get('name', 'Unknown')
        count = stats['count']
        alliance = user_info.get('allianceName', 'None')

        text += f"{i + 1}. {name} (ID: {user_id}) - {count} 个错误像素"
        if alliance and alliance != 'None':
            text += f" [alliance: {alliance}]"
        text += "\n"
    return text


def crop_image(remote_image, template_image, offset_x, offset_y):
    """
    从远程图片中裁剪出与模板图片相同大小的区域
    
    Args:
        remote_image: 远程图片 (PIL Image)
        template_image: 模板图片 (PIL Image)
        offset_x: X轴偏移量
        offset_y: Y轴偏移量
    
    Returns:
        PIL.Image: 裁剪后的图片
    """
    # 获取模板图片尺寸
    template_width, template_height = template_image.size

    # 计算裁剪区域 (left, upper, right, lower)
    left = offset_x
    upper = offset_y
    right = left + template_width
    lower = upper + template_height

    # 裁剪图片
    cropped = remote_image.crop((left, upper, right, lower))
    return cropped


def collect_user_error_statistics(different_pixels):

    # 创建cloudscraper实例
    scraper = cloudscraper.create_scraper()

    # 用户统计字典
    user_stats = {}
    new_error_stats={}

    # 遍历每个错误像素坐标
    for i, (x, y) in enumerate(different_pixels):
        try:

            # 构造请求URL
            url = f"https://backend.wplace.live/s0/pixel/{config['TlX']}/{config['TlY']}?x={x}&y={y}"

            # 发送请求
            response = scraper.get(url)
            response.raise_for_status()

            # 解析响应
            pixel_data = response.json()

            # 获取绘制用户信息
            painted_by = pixel_data.get('paintedBy', {})
            user_id = painted_by.get('id')

            if user_id:
                # 更新用户统计
                if user_id not in user_stats:
                    user_stats[user_id] = {
                        'count': 0,
                        'info': painted_by
                    }
                user_stats[user_id]['count'] += 1
                
                if (x,y) not in previous_error_pixels:
                    if user_id not in new_error_stats:
                        new_error_stats[user_id] = {
                            'count': 0,
                            'info': painted_by
                        }
                    new_error_stats[user_id]['count'] += 1
            else:
                # 处理未识别用户的情况
                if 'unknown' not in user_stats:
                    user_stats['unknown'] = {
                        'count': 0,
                        'info': {'name': 'Unknown', 'id': 'unknown'}
                    }
                user_stats['unknown']['count'] += 1

        except Exception as e:
            print(f"处理像素 ({x}, {y}) 时出错: {e}")
            continue

    return user_stats,new_error_stats


def compare_images_with_offset(remote_image, template_image, offset_x, offset_y):
    """
    比较两张图片，应用偏移量，跳过透明像素，记录不同像素坐标
    
    Args:
        remote_image: 远程图片 (PIL Image)
        template_image: 模板图片 (PIL Image)
        offset_x: X轴偏移量
        offset_y: Y轴偏移量
    
    Returns:
        list: 不同像素的坐标列表 [(x, y), ...]
    """
    # 转换为RGBA模式以处理透明度
    remote_image = remote_image.convert('RGBA')
    template_image = template_image.convert('RGBA')

    # 获取图片尺寸
    remote_width, remote_height = remote_image.size
    template_width, template_height = template_image.size

    different_pixels = []

    # 遍历模板图片的每个像素
    for tx in range(template_width):
        for ty in range(template_height):
            # 计算在远程图片中的对应坐标（应用偏移量）
            rx = tx + offset_x
            ry = ty + offset_y

            # 检查坐标是否在远程图片范围内
            if 0 <= rx < remote_width and 0 <= ry < remote_height:
                # 获取像素值 (R, G, B, A)
                template_pixel = template_image.getpixel((tx, ty))
                remote_pixel = remote_image.getpixel((rx, ry))

                # 检查模板像素是否透明 (Alpha = 0)
                if template_pixel[3] == 0:  # 跳过透明像素
                    continue

                # 比较非透明像素
                if template_pixel != remote_pixel:
                    # 记录不同的像素坐标（相对于远程图片）
                    different_pixels.append((rx, ry))

    return different_pixels


def download_image(tlx, tly):
    url = f"https://backend.wplace.live/files/s0/tiles/{tlx}/{tly}.png"
    response = requests.get(url)
    response.raise_for_status()
    image = Image.open(BytesIO(response.content))
    return image


def load_template(template_path):
    try:
        template = Image.open(template_path)
        return template
    except Exception as e:
        print(f"加载模板图片失败: {e}")
        return None


if __name__ == '__main__':
    m()
